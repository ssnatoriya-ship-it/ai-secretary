-- 顧客返信履歴 Phase1: 返信履歴専用テーブル（Supabase SQL Editorで手動実行してください）
-- 既存の schedules / tasks / memos / ideas / editorial_articles と同じ user_id + RLS パターンを踏襲する。
-- 既存テーブル（memosを含む）への変更は一切含まない。新規テーブルの追加のみ。
-- 既存のメモに残っている過去の顧客返信ログは削除・移行しない（customer-reply-history-implementation-plan.md参照）。

create table if not exists public.customer_replies (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  ai_secretary_id text not null default '',
  customer_name text not null default '',
  channel text not null default '',
  content text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.customer_replies enable row level security;

create policy "customer_replies_select_own" on public.customer_replies
  for select using (auth.uid() = user_id);

create policy "customer_replies_insert_own" on public.customer_replies
  for insert with check (auth.uid() = user_id);

create policy "customer_replies_update_own" on public.customer_replies
  for update using (auth.uid() = user_id);

create policy "customer_replies_delete_own" on public.customer_replies
  for delete using (auth.uid() = user_id);

-- 顧客ごとの履歴を新しい順に取得する用途を想定した複合index
create index if not exists customer_replies_user_customer_idx
  on public.customer_replies (user_id, ai_secretary_id, created_at desc);
