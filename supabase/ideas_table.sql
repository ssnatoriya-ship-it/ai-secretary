-- フェーズ1: アイデア機能用テーブル（Supabase SQL Editorで手動実行してください）
-- 既存の schedules / tasks / memos と同じ user_id + RLS パターンを踏襲する。
-- Claude API呼び出し・Obsidian保存には一切関与しない、最小入力保存のみのテーブル。

create table if not exists public.ideas (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  content text not null default '',
  status text not null default 'captured',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.ideas enable row level security;

create policy "ideas_select_own" on public.ideas
  for select using (auth.uid() = user_id);

create policy "ideas_insert_own" on public.ideas
  for insert with check (auth.uid() = user_id);

create policy "ideas_update_own" on public.ideas
  for update using (auth.uid() = user_id);

create policy "ideas_delete_own" on public.ideas
  for delete using (auth.uid() = user_id);
