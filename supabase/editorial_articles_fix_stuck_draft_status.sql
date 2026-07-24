-- 公開済み（published_urlが登録済み）にもかかわらず、workflow_status='draft'のまま
-- 残ってしまった記事をpublishedへ補正する。
-- Supabase SQL Editorで手動実行してください（自動実行しません）。
--
-- 背景：以前の実装では「再編集」ボタンを押した瞬間にworkflow_statusをdraftへ切り替えていた。
-- 保存せず離脱した場合（別画面へ移動・タブを閉じる・「クリア」を押す・保存失敗後の放置等）に
-- draftのまま戻らなくなる不具合があり、実際には公開済みの記事にも「下書き」バッジが
-- 表示されていた（blog-workflow-status-draft-fix-report.md参照）。
-- この構造自体は修正済み（「再編集」開始時にDBのworkflow_statusを変更しなくなった）だが、
-- 既に本番データに残ってしまったdraftの記事はこのSQLで一度だけ補正する必要がある。
--
-- 対象：published_urlが空でなく、かつworkflow_status='draft'の記事のみ。
-- published_urlが空欄の記事（本当に未公開の下書き）は対象外（変更しない）。

update public.editorial_articles
set workflow_status = 'published',
    updated_at = now()
where workflow_status = 'draft'
  and published_url is not null
  and published_url <> '';

-- 実行前に対象件数を確認したい場合は、まず以下のSELECTで確認してから実行してください。
--
-- select id, blog_title, published_url, workflow_status
-- from public.editorial_articles
-- where workflow_status = 'draft'
--   and published_url is not null
--   and published_url <> '';
