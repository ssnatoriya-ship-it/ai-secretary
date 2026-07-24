-- イベント管理 Phase1: メーカー・展示会・受注会と連絡希望顧客の紐付け専用テーブル
-- （Supabase SQL Editorで手動実行してください。自動実行はしません）。
-- 既存テーブル（customer_correspondences・customer_replies等）への変更は一切含まない。
-- 新規テーブル3つの追加のみ（event-customer-link-management-phase1-report.md参照）。
--
-- events: イベント（展示会・受注会等）本体。開催時期が未定・時期のみ判明の状態でも
-- 登録できるよう、start_date/end_dateは必須にしない（date_modeで区別する）。
create table if not exists public.events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  supplier text,
  season_label text,
  -- status候補: unannounced(未発表) / date_confirmed(日程決定) / inviting(案内中) /
  -- completed(終了) / cancelled(中止)
  status text not null default 'unannounced',
  -- date_mode候補: undecided(未定) / approximate(時期のみ) / fixed(日程確定)
  date_mode text not null default 'undecided',
  target_period text,
  start_date date,
  end_date date,
  description text,
  internal_memo text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  announced_at timestamptz,
  completed_at timestamptz
);

-- event_brands: イベントの対象ブランド（1イベントに複数登録可）。
-- 同一イベント内で同じブランド名を重複登録できないようにする。
create table if not exists public.event_brands (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  event_id uuid not null references public.events(id) on delete cascade,
  brand_name text not null,
  created_at timestamptz not null default now(),
  unique (event_id, brand_name)
);

-- event_watchers: イベントへの連絡希望顧客。顧客本体（Obsidian側の別システム）は
-- 参照するだけで、このテーブルからは一切削除・変更しない。
create table if not exists public.event_watchers (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  event_id uuid not null references public.events(id) on delete cascade,
  ai_secretary_id text,
  customer_name text not null,
  -- contact_status候補: waiting(未連絡) / contacted(連絡済) / reserved(予約済) / declined(辞退)
  contact_status text not null default 'waiting',
  memo text,
  contacted_at timestamptz,
  reserved_at timestamptz,
  declined_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 重複追加防止：顧客IDが判明している場合はID単位で、未判明の場合のみ氏名完全一致で
-- 同一イベント内の重複を防ぐ（1つのunique制約ではID優先/氏名フォールバックの
-- 両方を同時に表現できないため、部分インデックス2本に分ける）。
create unique index if not exists event_watchers_event_aisecretaryid_uniq
  on public.event_watchers (event_id, ai_secretary_id)
  where ai_secretary_id is not null;
create unique index if not exists event_watchers_event_customername_uniq
  on public.event_watchers (event_id, customer_name)
  where ai_secretary_id is null;

alter table public.events enable row level security;
alter table public.event_brands enable row level security;
alter table public.event_watchers enable row level security;

create policy "events_select_own" on public.events
  for select using (auth.uid() = user_id);
create policy "events_insert_own" on public.events
  for insert with check (auth.uid() = user_id);
create policy "events_update_own" on public.events
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "events_delete_own" on public.events
  for delete using (auth.uid() = user_id);

create policy "event_brands_select_own" on public.event_brands
  for select using (auth.uid() = user_id);
create policy "event_brands_insert_own" on public.event_brands
  for insert with check (auth.uid() = user_id);
create policy "event_brands_update_own" on public.event_brands
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "event_brands_delete_own" on public.event_brands
  for delete using (auth.uid() = user_id);

create policy "event_watchers_select_own" on public.event_watchers
  for select using (auth.uid() = user_id);
create policy "event_watchers_insert_own" on public.event_watchers
  for insert with check (auth.uid() = user_id);
create policy "event_watchers_update_own" on public.event_watchers
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "event_watchers_delete_own" on public.event_watchers
  for delete using (auth.uid() = user_id);

-- イベント一覧の状態フィルター・並び替え用。
create index if not exists events_user_status_idx
  on public.events (user_id, status, updated_at desc);

-- 対象ブランドの取得用（1イベント分をまとめて取得）。
create index if not exists event_brands_user_event_idx
  on public.event_brands (user_id, event_id);

-- イベント詳細の連絡希望顧客一覧・未連絡数の集計用。
create index if not exists event_watchers_user_event_idx
  on public.event_watchers (user_id, event_id, contact_status);

-- 「顧客管理」画面の「監視中イベント」セクション（顧客ID優先→氏名一致）用。
create index if not exists event_watchers_user_aisecretaryid_idx
  on public.event_watchers (user_id, ai_secretary_id);
create index if not exists event_watchers_user_customername_idx
  on public.event_watchers (user_id, customer_name);
