// Configuração do painel online (GitHub Pages).
// Cole aqui a chave PÚBLICA do Supabase (Project Settings -> API Keys):
// a "publishable" (começa com sb_publishable_) ou a antiga "anon public" (começa com eyJ).
// NUNCA cole aqui a chave secret/service_role.
// A chave anon é pública por natureza: com o SQL do setup ela só consegue LER os dados do robô.
window.PAINEL = {
  fonte: "supabase",
  url: "https://plbtilpkajfqpqtssluz.supabase.co",
  anonKey: "COLE_AQUI_A_CHAVE_PUBLICA",
  modo: "paper",
};
