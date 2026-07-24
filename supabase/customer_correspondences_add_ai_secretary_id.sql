-- 顧客対応案件（customer_correspondences）へ、顧客ID（NTR-XXXXXX形式）の列を追加する。
-- Supabase SQL Editorで手動実行してください（自動実行しません）。
--
-- 目的：「メール返信」画面の「過去のやり取り」機能で、顧客IDが判明している場合は
-- 氏名一致ではなくID完全一致で照合できるようにする（同姓同名の別顧客の対応履歴が
-- 混在することを防ぐ。customer-reply-inline-history-report.md参照）。
-- customer_repliesの ai_secretary_id 列と同じ考え方・同じ列名を採用する。
--
-- 既存行は null のままで構わない（保存済みの案件は氏名一致のフォールバックで
-- 引き続き履歴に表示される）。新規保存・再編集保存時、顧客が判明している場合のみ値が入る。

alter table public.customer_correspondences
  add column if not exists ai_secretary_id text;

-- 「過去のやり取り」のID照合クエリで使う。
create index if not exists customer_correspondences_user_aisecretaryid_idx
  on public.customer_correspondences (user_id, ai_secretary_id);
