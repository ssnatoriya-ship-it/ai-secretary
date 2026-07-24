-- 編集部AI記事ライブラリ Phase1: 記事保存用テーブル（Supabase SQL Editorで手動実行してください）
-- 既存の schedules / tasks / memos / ideas と同じ user_id + RLS パターンを踏襲する。
-- 既存テーブルへの変更は一切含まない。新規テーブルの追加のみ。

create table if not exists public.editorial_articles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  product_name text not null default '',
  product_url text not null default '',
  blog_title text not null default '',
  seo_title text not null default '',
  description text not null default '',
  keywords text not null default '',
  blog_html text not null default '',
  x_post text not null default '',
  instagram_caption text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.editorial_articles enable row level security;

create policy "editorial_articles_select_own" on public.editorial_articles
  for select using (auth.uid() = user_id);

create policy "editorial_articles_insert_own" on public.editorial_articles
  for insert with check (auth.uid() = user_id);

create policy "editorial_articles_update_own" on public.editorial_articles
  for update using (auth.uid() = user_id);

create policy "editorial_articles_delete_own" on public.editorial_articles
  for delete using (auth.uid() = user_id);

-- 一覧表示（自分の記事を新しい順に取得）を高速化するための複合index
create index if not exists editorial_articles_user_created_idx
  on public.editorial_articles (user_id, created_at desc);
