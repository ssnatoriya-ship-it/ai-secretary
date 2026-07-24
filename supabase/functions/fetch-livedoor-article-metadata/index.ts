// Supabase Edge Function: fetch-livedoor-article-metadata
//
// 公開済みライブドアブログ記事のURLから、タイトル・OGP画像・拍手数をまとめて取得する
// （livedoor-public-metadata-auto-fetch-report.md参照）。
//
// 既存のfetch-livedoor-applauseとは責務を分離した別関数として実装する。
// 既存関数の安定稼働を優先し、このファイルはfetch-livedoor-applause/index.tsを
// 一切変更・依存しない（共通モジュール化もしない）。SSRF対策・GET専用読み取りなど、
// 一部のロジックはこのファイル内に意図的に複製している。
//
// 安全要件:
// - ライブドアブログへの通信はGETのみ。POST（拍手を増やす通信・記事投稿・編集）は一切行わない。
// - 任意の外部URLを取得できる汎用プロキシにしない。
//   - 記事HTML取得先：published_urlが https + *.livedoor.blog + /archives/{数字}.html のときのみ許可。
//   - OGP画像取得先：記事HTML内から抽出したURLであっても、ホスト名が
//     livedoor.blogimg.jp（またはそのサブドメイン）でない限り取得しない
//     （og:image はページ所有者が自由に設定できる「攻撃者が影響を与えられるコンテンツ」のため、
//     published_urlの検証とは独立したSSRF対策が必要。実記事のog:imageを実機確認し、
//     実際のホスト名がlivedoor.blogimg.jpであることを確認済み）。
// - localhost・プライベートIP・file:・data:・javascript:等のスキームは、https限定
//   ＋ホスト名の完全一致/サフィックス一致チェックにより構造的に到達不能。
// - タイムアウト・レスポンスサイズ上限（記事HTML・画像それぞれ別上限）を設定する。
// - 画像はContent-Typeがimage/jpeg・image/png・image/webpのいずれかの場合のみ受け付ける。
// - 記事本文の全文はレスポンスに含めない（タイトル・画像URL・拍手数・タイムスタンプのみ返す）。
// - 認証：AI秘書へログイン中のユーザーのみ呼び出せる（匿名利用不可）。
// - エラー時、内部情報（例外メッセージ・スタックトレース）は利用者へ返さない
//   （console.errorでFunctionのログにのみ出力する）。
// - サムネイルは、呼び出し元が渡したarticle_idに紐づく記事に、現在サムネイルが
//   未設定の場合のみ保存する。既存サムネイルは絶対に上書きしない。
//   article_idが渡されない場合（未保存の新規記事など）は、サムネイル保存を一切行わない。
//
// デプロイ方法・Secrets設定は実装レポートを参照。追加のSecrets設定は不要
// （SUPABASE_URL・SUPABASE_ANON_KEYはEdge Functionへ自動的に注入される）。

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const ALLOWED_ARTICLE_HOST_PATTERN = /^[a-z0-9-]+\.livedoor\.blog$/i;
const ARTICLE_PATH_PATTERN = /^\/archives\/(\d+)\.html$/;
// 実際の公開記事のog:imageを実機確認した結果に基づく許可ホスト（サブドメインも許可する）。
const ALLOWED_IMAGE_HOST_PATTERN = /(^|\.)livedoor\.blogimg\.jp$/i;
const ALLOWED_IMAGE_CONTENT_TYPES = ["image/jpeg", "image/png", "image/webp"];

const FETCH_TIMEOUT_MS = 8000;
// 実際のライブドア記事HTMLは10KBを超えることが多く、旧上限（10KB）では
// og:title・og:imageの手前で読み取りが打ち切られて失敗していた。512KBへ引き上げる
// （ただし早期終了ロジックにより、通常はここまで読み切る前にhead内で完了する）。
const MAX_ARTICLE_HTML_BYTES = 512 * 1024;
const MAX_APPLAUSE_RESPONSE_BYTES = 10 * 1024;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const THUMBNAIL_BUCKET = "editorial-thumbnails";
const GENERIC_ERROR = "公開情報を取得できませんでした";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
}

// published_urlを検証し、{ blogId, articleId } を返す。不正な場合はnullを返す。
// fetch-livedoor-applauseのparsePublishedUrl()と同じロジック（既存関数を変更しないため複製）。
function parsePublishedUrl(publishedUrl: unknown): { blogId: string; articleId: string } | null {
  if (typeof publishedUrl !== "string" || publishedUrl.length === 0 || publishedUrl.length > 500) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(publishedUrl);
  } catch {
    return null;
  }
  if (url.protocol !== "https:") return null;
  if (!ALLOWED_ARTICLE_HOST_PATTERN.test(url.hostname)) return null;

  const pathMatch = url.pathname.match(ARTICLE_PATH_PATTERN);
  if (!pathMatch) return null;

  const blogId = url.hostname.slice(0, url.hostname.length - ".livedoor.blog".length);
  if (!/^[a-z0-9-]+$/i.test(blogId)) return null;

  return { blogId, articleId: pathMatch[1] };
}

// OGP画像URLがSSRF対策上許可されたホストかどうかを検証する。
// published_urlの検証とは独立して行う（記事HTML内のog:imageは記事所有者が自由に
// 設定できるコンテンツであり、published_urlがlivedoor.blog配下であることの検証だけでは
// 画像URLの安全性を担保できないため）。
function isAllowedImageUrl(imageUrl: string): boolean {
  let url: URL;
  try {
    url = new URL(imageUrl);
  } catch {
    return false;
  }
  if (url.protocol !== "https:") return false;
  return ALLOWED_IMAGE_HOST_PATTERN.test(url.hostname);
}

// レスポンスボディを上限バイト数まで読み取り、超過した場合は打ち切る（レスポンスサイズ上限）。
// バイナリ（画像）にも使えるよう、テキストではなくUint8Arrayで返す。
async function readBodyWithLimit(res: Response, maxBytes: number): Promise<Uint8Array> {
  if (!res.body) return new Uint8Array(0);
  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    received += value.byteLength;
    if (received > maxBytes) {
      await reader.cancel();
      throw new Error("response too large");
    }
    chunks.push(value);
  }
  const combined = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return combined;
}

async function fetchWithTimeout(url: string, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { method: "GET", signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
}

function decodeHtmlEntities(s: string): string {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&#x([0-9a-f]+);/gi, (_m, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_m, dec) => String.fromCodePoint(parseInt(dec, 10)));
}

// <meta property="X" content="Y"> / <meta name="X" content="Y"> のcontent値を抽出する。
// 属性の出現順序（property/nameが先かcontentが先か）のどちらにも対応する簡易パーサー。
// attrNamesは優先順位順に並んだ候補配列（最初に見つかったものを採用する）。
function extractMetaContent(html: string, attrNames: string[]): string | null {
  for (const attrName of attrNames) {
    const escaped = attrName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re1 = new RegExp(`<meta[^>]+(?:property|name)=["']${escaped}["'][^>]*content=["']([^"']*)["']`, "i");
    const m1 = html.match(re1);
    if (m1 && m1[1]) return decodeHtmlEntities(m1[1].trim());
    const re2 = new RegExp(`<meta[^>]+content=["']([^"']*)["'][^>]*(?:property|name)=["']${escaped}["']`, "i");
    const m2 = html.match(re2);
    if (m2 && m2[1]) return decodeHtmlEntities(m2[1].trim());
  }
  return null;
}

// タイトル抽出の優先順位：1. og:title 2. <title> 3. 記事見出し(h1) 4. null
function extractTitle(html: string): string | null {
  const ogTitle = extractMetaContent(html, ["og:title"]);
  if (ogTitle) return ogTitle;

  const titleMatch = html.match(/<title[^>]*>([^<]*)<\/title>/i);
  if (titleMatch && titleMatch[1].trim()) return decodeHtmlEntities(titleMatch[1].trim());

  const h1Match = html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i);
  if (h1Match) {
    const text = h1Match[1].replace(/<[^>]+>/g, "").trim();
    if (text) return decodeHtmlEntities(text);
  }
  return null;
}

// OGP画像URL抽出の優先順位：1. og:image 2. twitter:image / twitter:image:src 3. null
// 実記事を確認したところ、実際のタグ名はtwitter:image:src（twitter:imageではない）だったため、
// 両方の名前を候補に含める（仕様上はtwitter:imageと記載されているが、実データとの乖離に
// 対応するため両対応とする）。
function extractOgImage(html: string): string | null {
  return extractMetaContent(html, ["og:image", "twitter:image:src", "twitter:image"]);
}

// 記事HTMLをGETで取得し、チャンクごとにタイトル・OGP画像の両方が抽出できた時点で
// 読み取りを打ち切る（不要な全文取得・全文解析を行わない）。og:title・og:image等の
// metaタグは通常<head>内、つまりページ冒頭にあるため、多くの記事はごく一部の読み取りだけで
// 完了する。見つからないまま読み進めた場合は、MAX_ARTICLE_HTML_BYTESに達した時点で
// 「response too large」として打ち切る（SSRF対策・レスポンスサイズ上限は現状維持）。
async function fetchArticleHtmlUntilMetadataFound(url: string, maxBytes: number, timeoutMs: number): Promise<string> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { method: "GET", signal: controller.signal });
    if (!res.ok) throw new Error(`upstream status ${res.status}`);
    if (!res.body) return "";

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let html = "";
    let received = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      received += value.byteLength;
      if (received > maxBytes) {
        await reader.cancel();
        throw new Error("response too large");
      }
      html += decoder.decode(value, { stream: true });

      if (extractTitle(html) && extractOgImage(html)) {
        await reader.cancel();
        return html;
      }
    }
    return html;
  } finally {
    clearTimeout(timeoutId);
  }
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: CORS_HEADERS });
  }
  if (req.method !== "POST") {
    return jsonResponse({ ok: false, error: GENERIC_ERROR }, 405);
  }

  // 認証：AI秘書へログイン中のユーザーのみ許可する（匿名利用は許可しない）。
  const authHeader = req.headers.get("Authorization");
  if (!authHeader) {
    return jsonResponse({ ok: false, error: GENERIC_ERROR }, 401);
  }
  const supabaseClient = createClient(
    Deno.env.get("SUPABASE_URL") ?? "",
    Deno.env.get("SUPABASE_ANON_KEY") ?? "",
    { global: { headers: { Authorization: authHeader } } },
  );
  const { data: userData, error: userError } = await supabaseClient.auth.getUser();
  if (userError || !userData?.user) {
    return jsonResponse({ ok: false, error: GENERIC_ERROR }, 401);
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return jsonResponse({ ok: false, error: GENERIC_ERROR }, 400);
  }

  const publishedUrl = (body as Record<string, unknown> | null)?.published_url;
  const parsed = parsePublishedUrl(publishedUrl);
  if (!parsed) {
    return jsonResponse({ ok: false, error: GENERIC_ERROR }, 400);
  }
  // article_idは呼び出し元（クライアント）が既に把握している記事の内部ID。
  // サムネイル保存の対象行を一意に特定するために使う（published_urlでの曖昧な一致検索は行わない）。
  // 渡されない場合（未保存の新規記事フォームなど）は、サムネイル保存を一切試みない。
  const rawArticleId = (body as Record<string, unknown> | null)?.article_id;
  const articleId = typeof rawArticleId === "string" && rawArticleId.length > 0 ? rawArticleId : null;

  // 1. 記事HTMLを取得する（GETのみ）。取得先はpublished_url自体（既に検証済み）。
  //    タイトル・OGP画像の両方が見つかった時点で読み取りを打ち切るため、
  //    通常は512KBの上限まで読み切ることなく完了する。
  let articleHtml: string;
  try {
    articleHtml = await fetchArticleHtmlUntilMetadataFound(publishedUrl as string, MAX_ARTICLE_HTML_BYTES, FETCH_TIMEOUT_MS);
  } catch (e) {
    console.error("[fetch-livedoor-article-metadata] article fetch failed", e);
    return jsonResponse({ ok: false, error: GENERIC_ERROR }, 502);
  }

  const title = extractTitle(articleHtml);
  const ogImageUrl = extractOgImage(articleHtml);

  // 2. 拍手数を取得する（GETのみ。fetch-livedoor-applauseと同じ取得先・同じロジック）。
  //    拍手数の取得に失敗しても、タイトル・OGP画像の取得結果は破棄せず返す（部分的成功を許容）。
  let applauseCount: number | null = null;
  try {
    const clapUrl = `https://clap.blogcms.jp/livedoor/${parsed.blogId}/${parsed.articleId}/?_=${Date.now()}`;
    const res = await fetchWithTimeout(clapUrl, FETCH_TIMEOUT_MS);
    if (res.ok) {
      const bytes = await readBodyWithLimit(res, MAX_APPLAUSE_RESPONSE_BYTES);
      const text = new TextDecoder().decode(bytes);
      const data = JSON.parse(text);
      const rawCount = Number((data as Record<string, unknown> | null)?.count);
      if (Number.isFinite(rawCount)) applauseCount = Math.max(0, Math.floor(rawCount));
    }
  } catch (e) {
    console.error("[fetch-livedoor-article-metadata] applause fetch failed", e);
  }

  // 3. サムネイル保存（article_idが渡されており、かつ対象記事に現在サムネイルが未設定の場合のみ）。
  //    既存サムネイルは絶対に上書きしない。
  let thumbnailSaved = false;
  let thumbnailPath: string | null = null;
  if (articleId && ogImageUrl && isAllowedImageUrl(ogImageUrl)) {
    try {
      const { data: articleRow } = await supabaseClient
        .from("editorial_articles")
        .select("id, thumbnail_path")
        .eq("id", articleId)
        .eq("user_id", userData.user.id)
        .maybeSingle();

      if (articleRow && !articleRow.thumbnail_path) {
        const imgRes = await fetchWithTimeout(ogImageUrl, FETCH_TIMEOUT_MS);
        if (imgRes.ok) {
          const contentType = (imgRes.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
          if (ALLOWED_IMAGE_CONTENT_TYPES.includes(contentType)) {
            const imageBytes = await readBodyWithLimit(imgRes, MAX_IMAGE_BYTES);
            const ext = contentType === "image/png" ? "png" : contentType === "image/webp" ? "webp" : "jpg";
            const path = `${userData.user.id}/${articleRow.id}/${crypto.randomUUID()}.${ext}`;
            const { error: uploadError } = await supabaseClient.storage
              .from(THUMBNAIL_BUCKET)
              .upload(path, imageBytes, { contentType });
            if (!uploadError) {
              thumbnailSaved = true;
              thumbnailPath = path;
            } else {
              console.error("[fetch-livedoor-article-metadata] thumbnail upload failed", uploadError);
            }
          }
        }
      }
    } catch (e) {
      console.error("[fetch-livedoor-article-metadata] thumbnail fetch/save failed", e);
      // サムネイル取得・保存に失敗しても、タイトル・拍手数の取得結果はそのまま返す。
    }
  }

  return jsonResponse(
    {
      ok: true,
      article_id: parsed.articleId,
      title,
      og_image_url: ogImageUrl,
      applause_count: applauseCount,
      checked_at: new Date().toISOString(),
      thumbnail_saved: thumbnailSaved,
      thumbnail_path: thumbnailPath,
    },
    200,
  );
});
