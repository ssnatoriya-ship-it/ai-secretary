-- ブログ書庫からブログ作成へ戻す機能（再編集ワークフロー）のための列を追加する
-- Supabase SQL Editorで手動実行してください。
-- 既存の editorial_articles テーブルへの列追加のみ。他の列・他のテーブルへの変更は含まない。
--
-- デフォルト値・NOT NULL制約はあえて付けない。既存記事はnullのまま残り、
-- アプリ側のコード（ArticleStore._fromDb()）がnullを'published'として扱うことで
-- 後方互換性を担保する（blog-workflow-redesign-report.md参照）。
--
-- 値の意味：
--   'published'（またはnull）：ブログ書庫に保存済みの記事
--   'draft'：ブログ書庫の「再編集」から戻され、ブログ作成画面で編集中の記事

alter table public.editorial_articles
  add column if not exists workflow_status text;
