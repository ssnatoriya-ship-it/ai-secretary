-- 調査部門兼WEBカタログ作成チーム Phase1: 商品カタログ保存用テーブル
-- （Supabase SQL Editorで手動実行してください）
-- 既存の schedules / tasks / memos / ideas / editorial_articles / customer_replies と
-- 同じ user_id + RLS パターンを踏襲する。既存テーブルへの変更は一切含まない。
--
-- Phase1では brand〜research_notes_input・rating・edit_history・created_at/updated_at のみ使用する。
-- それ以外の列（spec_html〜spec_id）はPhase2以降（AI生成・画像解析・Web調査）で使用する
-- 拡張用の列で、Phase1のコードからは一切書き込まない
-- （catalog-production-phase1-readiness.md参照）。
-- 写真保存用のcatalog_product_photosテーブルは、写真アップロード機能を実装するPhase2で作成する。

create table if not exists public.catalog_products (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,

  -- Phase1で使用：入力項目
  brand text not null default '',
  product_name text not null default '',
  model_number text not null default '',
  category text not null default '',
  known_specs text not null default '',
  supplementary_info text not null default '',
  reference_urls text not null default '',
  research_notes_input text not null default '',

  -- Phase2以降で使用：AI生成結果（Phase1では常に既定値のまま）
  spec_html text not null default '',
  primary_color text not null default '',
  description_1_title text not null default '',
  description_1_body text not null default '',
  description_2_title text not null default '',
  description_2_body text not null default '',
  description_3_title text not null default '',
  description_3_body text not null default '',
  seo_title text not null default '',
  seo_description text not null default '',
  keywords text not null default '',
  research_notes_output text not null default '',
  information_sources text not null default '',
  confidence_notes text not null default '',
  spec_data jsonb not null default '[]'::jsonb,
  badge_data jsonb not null default '[]'::jsonb,
  chip_data jsonb not null default '[]'::jsonb,
  field_review_status jsonb not null default '{}'::jsonb,
  unconfirmed_items jsonb not null default '[]'::jsonb,
  has_unconfirmed_info boolean not null default false,
  spec_id text not null default '',

  -- Phase1で使用
  rating integer,
  edit_history jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint catalog_products_rating_range check (rating is null or (rating >= 1 and rating <= 5))
);

alter table public.catalog_products enable row level security;

create policy "catalog_products_select_own" on public.catalog_products
  for select using (auth.uid() = user_id);

create policy "catalog_products_insert_own" on public.catalog_products
  for insert with check (auth.uid() = user_id);

create policy "catalog_products_update_own" on public.catalog_products
  for update using (auth.uid() = user_id);

create policy "catalog_products_delete_own" on public.catalog_products
  for delete using (auth.uid() = user_id);

-- 一覧表示（自分の商品カタログを新しい順に取得）を高速化するための複合index
create index if not exists catalog_products_user_created_idx
  on public.catalog_products (user_id, created_at desc);
