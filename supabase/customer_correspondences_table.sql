-- 顧客対応管理 Phase1: 顧客対応案件専用テーブル（Supabase SQL Editorで手動実行してください）
-- 既存の schedules / tasks / memos / ideas / editorial_articles / customer_replies と同じ
-- user_id + RLS パターンを踏襲する。既存テーブル（customer_repliesを含む）への変更は
-- 一切含まない。新規テーブルの追加のみ（customer-correspondence-management-phase1-report.md参照）。
--
-- customer_repliesとの違い：customer_repliesは「送った返信文のログ」のみを保持する
-- 軽量な履歴テーブル（変更なし・維持）。customer_correspondencesは「対応状況・次回対応日・
-- フォロー期限・長期監視案件」まで含めて管理する、案件単位の管理テーブル。

create table if not exists public.customer_correspondences (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  customer_name text not null,
  subject text,
  inquiry_text text,
  reply_text text,
  -- status候補: unhandled(未対応) / ongoing(返信済・継続中) / waiting(返信待ち) /
  -- monitoring(監視中) / completed(完了)
  status text not null default 'unhandled',
  next_action_date date,
  follow_up_deadline date,
  -- 曖昧な予定時期を自由文で保存する（例：「10月頃」「秋頃」「オーダー会開催時」）。
  -- Phase1では日付への自動変換は行わない。
  target_period text,
  monitoring_note text,
  memo text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz
);

alter table public.customer_correspondences enable row level security;

create policy "customer_correspondences_select_own" on public.customer_correspondences
  for select using (auth.uid() = user_id);
create policy "customer_correspondences_insert_own" on public.customer_correspondences
  for insert with check (auth.uid() = user_id);
create policy "customer_correspondences_update_own" on public.customer_correspondences
  for update using (auth.uid() = user_id);
create policy "customer_correspondences_delete_own" on public.customer_correspondences
  for delete using (auth.uid() = user_id);

-- 顧客対応書庫の一覧・状態フィルター・アラート集計で使う主要な検索パターン用。
create index if not exists customer_correspondences_user_status_idx
  on public.customer_correspondences (user_id, status, next_action_date);

-- 「この顧客の過去対応」表示（customer_name完全一致検索）用。
create index if not exists customer_correspondences_user_customer_idx
  on public.customer_correspondences (user_id, customer_name, created_at desc);
