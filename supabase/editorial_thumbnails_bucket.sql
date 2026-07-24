-- ブログ書庫のサムネイル画像用Storageバケットを作成する
-- Supabaseダッシュボードまたは SQL Editor で手動実行してください。まだ作成・実行していません。
-- 商品カタログのcatalog-photosバケットと同じ設計方針（非公開・{user_id}/配下にパスを限定）を踏襲する
-- （catalog-production-phase3a1-storage-design.md、blog-publication-thumbnail-applause-management-report.md参照）。
--
-- 保存パス規則：{user_id}/{editorial_article_id}/{uuid}.jpg
-- 公開／非公開：非公開（サムネイルの中身が非公開のライブドア記事に紐づくため、念のため非公開で運用する）

-- 1. バケット作成（ダッシュボードの「Storage」→「New bucket」から、
--    Name: editorial-thumbnails / Public: いいえ、として作成しても同じ結果になります）
insert into storage.buckets (id, name, public)
values ('editorial-thumbnails', 'editorial-thumbnails', false)
on conflict (id) do nothing;

-- 2. RLSポリシー（バケット作成後に実行してください）
-- 保存パスの先頭セグメント（{user_id}/...）がauth.uid()と一致する場合のみ、
-- select/insert/update/deleteを許可する。
create policy "editorial_thumbnails_select_own" on storage.objects
  for select using (
    bucket_id = 'editorial-thumbnails'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "editorial_thumbnails_insert_own" on storage.objects
  for insert with check (
    bucket_id = 'editorial-thumbnails'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "editorial_thumbnails_update_own" on storage.objects
  for update using (
    bucket_id = 'editorial-thumbnails'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "editorial_thumbnails_delete_own" on storage.objects
  for delete using (
    bucket_id = 'editorial-thumbnails'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
