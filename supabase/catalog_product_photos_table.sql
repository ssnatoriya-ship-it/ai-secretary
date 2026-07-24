-- 調査部門兼WEBカタログ作成チーム Phase3-A1: 商品写真保存用テーブル
-- （Supabase SQL Editorで手動実行してください）
-- 既存の schedules / tasks / memos / ideas / editorial_articles / customer_replies / catalog_products と
-- 同じ user_id + RLS パターンを踏襲する。既存テーブルへの変更は一切含まない。
--
-- Phase3-A1ではこのテーブルとStorage設計のみを行う。写真アップロードUI・画像前処理・
-- AIによる画像解析（Phase3-A2以降）からは、まだ一切書き込まない
-- （catalog-production-phase3a1-storage-design.md参照）。
--
-- 実ファイルはSupabase Storageの非公開バケット「catalog-photos」に
-- {user_id}/{catalog_product_id}/{uuid}.jpg の形式で保存する想定で、この表は
-- そのメタデータ（Storage上のパス・表示順・役割・解析状態等）のみを保持する。

create table if not exists public.catalog_product_photos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  catalog_product_id uuid not null references public.catalog_products(id) on delete cascade,

  storage_path text not null default '',
  file_name text not null default '',
  mime_type text not null default '',
  width integer,
  height integer,
  file_size bigint,

  sort_order integer not null default 0,
  is_primary boolean not null default false,
  role text not null default '',
  analysis_status text not null default 'unanalyzed',

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint catalog_product_photos_analysis_status_check
    check (analysis_status in ('unanalyzed', 'analyzed')),
  constraint catalog_product_photos_role_check
    check (role in ('', '正面', '側面', 'ソール', '内装', 'ディテール', 'その他'))
);

alter table public.catalog_product_photos enable row level security;

create policy "catalog_product_photos_select_own" on public.catalog_product_photos
  for select using (auth.uid() = user_id);

create policy "catalog_product_photos_insert_own" on public.catalog_product_photos
  for insert with check (auth.uid() = user_id);

create policy "catalog_product_photos_update_own" on public.catalog_product_photos
  for update using (auth.uid() = user_id);

create policy "catalog_product_photos_delete_own" on public.catalog_product_photos
  for delete using (auth.uid() = user_id);

-- 商品編集画面での表示順・AI送信順の取得（catalog_product_idごとにsort_order順で取得）を高速化する
create index if not exists catalog_product_photos_product_sort_idx
  on public.catalog_product_photos (catalog_product_id, sort_order);

-- 1商品につきメイン画像（is_primary = true）は常に1枚だけに制限する
create unique index if not exists catalog_product_photos_primary_unique
  on public.catalog_product_photos (catalog_product_id)
  where is_primary = true;
