// Supabase Edge Function: fetch-livedoor-applause
//
// ライブドアブログの拍手数（GETのみ）をサーバー側で取得する。ブラウザから
// https://clap.blogcms.jp/ へ直接fetchするとCORSで失敗するため、このEdge Function経由で取得する。
//
// 安全要件（livedoor-applause-auto-fetch-implementation-report.md参照）:
// - POST（拍手を増やす通信）は絶対に実装しない。このファイルにはGET以外のfetchが存在しない。
// - 任意の外部URLを取得できる汎用プロキシにしない。取得先ホストは常に clap.blogcms.jp 固定。
// - SSRF対策：入力のpublished_urlはhttps・ライブドアブログのサブドメインのみ許可し、
//   そこから抽出した英数字・ハイフンのみの識別子で取得先URLを組み立てる
//   （localhost・プライベートIP・任意ホストへは構造的にアクセスできない）。
// - タイムアウト・レスポンスサイズ上限を設定する。
// - 認証：AI秘書へログイン中のユーザーのみ呼び出せる（匿名利用不可）。
// - エラー時、内部情報（例外メッセージ・スタックトレース）は利用者へ返さない
//   （console.errorでFunctionのログにのみ出力する）。
//
// デプロイ方法・Secrets設定は実装レポートを参照。追加のSecrets設定は不要
// （SUPABASE_URL・SUPABASE_ANON_KEYはEdge Functionへ自動的に注入される）。

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const ALLOWED_HOST_PATTERN = /^[a-z0-9-]+\.livedoor\.blog$/i;
const ARTICLE_PATH_PATTERN = /^\/archives\/(\d+)\.html$/;
const FETCH_TIMEOUT_MS = 8000;
const MAX_RESPONSE_BYTES = 10 * 1024; // 想定レスポンスは数十バイト程度のJSONのため十分な上限
const GENERIC_ERROR = "拍手数を取得できませんでした";

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
// SSRF対策：httpsのみ許可し、ホスト名をlivedoor.blogのサブドメインに厳密に限定する。
// これにより、localhost・プライベートIP・任意の外部ホストへは構造的にアクセスできない
// （常に固定ホストclap.blogcms.jpへ、検証済みの英数字・ハイフンのみのセグメントで
// URLを組み立てるため。javascript:・data:・file:等のスキームも protocol !== "https:" で拒否される）。
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
  if (!ALLOWED_HOST_PATTERN.test(url.hostname)) return null;

  const pathMatch = url.pathname.match(ARTICLE_PATH_PATTERN);
  if (!pathMatch) return null;

  // ブログ所有者名（blogId）はホスト名から特定する（例：natoriya.livedoor.blog → natoriya）。
  // 公開記事HTMLを別途取得して解析する経路は、追加の外部通信・HTML解析という新たな
  // 攻撃面を増やすだけで、ホスト名からの特定で十分安全・確実なため採用しない。
  const blogId = url.hostname.slice(0, url.hostname.length - ".livedoor.blog".length);
  if (!/^[a-z0-9-]+$/i.test(blogId)) return null;

  return { blogId, articleId: pathMatch[1] };
}

// レスポンスボディを上限バイト数まで読み取り、超過した場合は打ち切る（レスポンスサイズ上限）。
async function readBodyWithLimit(res: Response, maxBytes: number): Promise<string> {
  if (!res.body) return "";
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let received = 0;
  let text = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    received += value.byteLength;
    if (received > maxBytes) {
      await reader.cancel();
      throw new Error("response too large");
    }
    text += decoder.decode(value, { stream: true });
  }
  return text;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: CORS_HEADERS });
  }
  if (req.method !== "POST") {
    return jsonResponse({ ok: false, error: GENERIC_ERROR }, 405);
  }

  // 認証：AI秘書へログイン中のユーザーのみ許可する（匿名利用は許可しない）。
  // supabase.functions.invoke()はログイン中のセッションのアクセストークンを
  // 自動的にAuthorizationヘッダーへ付与するため、ここでそれを検証する。
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

  // GETのみ実行する。POST（拍手を増やす通信）は絶対に実行しない。
  const targetUrl = `https://clap.blogcms.jp/livedoor/${parsed.blogId}/${parsed.articleId}/?_=${Date.now()}`;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  let text: string;
  try {
    const res = await fetch(targetUrl, { method: "GET", signal: controller.signal });
    if (!res.ok) {
      return jsonResponse({ ok: false, error: GENERIC_ERROR }, 502);
    }
    text = await readBodyWithLimit(res, MAX_RESPONSE_BYTES);
  } catch (e) {
    console.error("[fetch-livedoor-applause] upstream fetch failed", e);
    return jsonResponse({ ok: false, error: GENERIC_ERROR }, 502);
  } finally {
    clearTimeout(timeoutId);
  }

  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (e) {
    console.error("[fetch-livedoor-applause] invalid JSON from upstream", e);
    return jsonResponse({ ok: false, error: GENERIC_ERROR }, 502);
  }

  if (typeof data !== "object" || data === null || !("count" in data)) {
    return jsonResponse({ ok: false, error: GENERIC_ERROR }, 502);
  }
  const rawCount = Number((data as Record<string, unknown>).count);
  if (!Number.isFinite(rawCount)) {
    return jsonResponse({ ok: false, error: GENERIC_ERROR }, 502);
  }
  const count = Math.max(0, Math.floor(rawCount));

  return jsonResponse(
    {
      ok: true,
      article_id: parsed.articleId,
      count,
      checked_at: new Date().toISOString(),
    },
    200,
  );
});
