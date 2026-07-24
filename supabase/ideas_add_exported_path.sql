-- フェーズ3: アイデア機能にObsidian保存パスを記録する列を追加する
-- Supabase SQL Editorで手動実行してください。
-- ideas.status は自由文字列のため、captured/drafted/exported/export_failed の
-- 追加値をそのまま利用できます（スキーマ変更は不要）。

alter table public.ideas add column if not exists exported_path text;
