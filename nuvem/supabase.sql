-- Rode este script UMA VEZ no Supabase: menu "SQL Editor" -> New query -> cole tudo -> Run.
-- Cria as tabelas do robô. O robô grava usando a chave service_role (secreta, só no GitHub).
-- O painel lê usando a chave anon (pública), que aqui só tem permissão de LEITURA.

create table if not exists robo_kv (
  chave text primary key,
  valor jsonb not null,
  atualizado_em timestamptz not null default now()
);

create table if not exists robo_trades (
  id bigserial primary key,
  modo text not null,
  entrada_em timestamptz, saida_em timestamptz,
  preco_entrada double precision, preco_saida double precision,
  qtd double precision, lucro double precision, motivo text
);

create table if not exists robo_patrimonio (
  id bigserial primary key,
  modo text not null,
  timestamp timestamptz, preco double precision, patrimonio double precision
);

create table if not exists robo_log (
  id bigserial primary key,
  modo text not null,
  criado_em timestamptz not null default now(),
  nivel text, mensagem text
);

create index if not exists robo_log_modo_id on robo_log (modo, id desc);
create index if not exists robo_trades_modo_id on robo_trades (modo, id desc);
create index if not exists robo_patrimonio_modo_id on robo_patrimonio (modo, id desc);

-- Segurança: liga o RLS e permite apenas LEITURA para o painel (anon).
alter table robo_kv enable row level security;
alter table robo_trades enable row level security;
alter table robo_patrimonio enable row level security;
alter table robo_log enable row level security;

drop policy if exists "painel le kv" on robo_kv;
drop policy if exists "painel le trades" on robo_trades;
drop policy if exists "painel le patrimonio" on robo_patrimonio;
drop policy if exists "painel le log" on robo_log;

-- O painel só enxerga o status (não o estado interno).
create policy "painel le kv" on robo_kv for select to anon using (chave like '%:status');
create policy "painel le trades" on robo_trades for select to anon using (true);
create policy "painel le patrimonio" on robo_patrimonio for select to anon using (true);
create policy "painel le log" on robo_log for select to anon using (true);

-- Limpeza: apaga log com mais de 30 dias (rode quando quiser).
-- delete from robo_log where criado_em < now() - interval '30 days';
