-- Painel com login: só usuários autenticados (o admin) leem os dados e podem pausar o robô.
-- Rode uma vez no SQL Editor do Supabase.

drop policy if exists "painel le kv" on robo_kv;
drop policy if exists "painel le trades" on robo_trades;
drop policy if exists "painel le patrimonio" on robo_patrimonio;
drop policy if exists "painel le log" on robo_log;
drop policy if exists "admin le kv" on robo_kv;
drop policy if exists "admin cria controle" on robo_kv;
drop policy if exists "admin altera controle" on robo_kv;
drop policy if exists "admin le trades" on robo_trades;
drop policy if exists "admin le patrimonio" on robo_patrimonio;
drop policy if exists "admin le log" on robo_log;

create policy "admin le kv" on robo_kv for select to authenticated
  using (chave like '%:status' or chave = 'controle');
create policy "admin cria controle" on robo_kv for insert to authenticated
  with check (chave = 'controle');
create policy "admin altera controle" on robo_kv for update to authenticated
  using (chave = 'controle') with check (chave = 'controle');
create policy "admin le trades" on robo_trades for select to authenticated using (true);
create policy "admin le patrimonio" on robo_patrimonio for select to authenticated using (true);
create policy "admin le log" on robo_log for select to authenticated using (true);
