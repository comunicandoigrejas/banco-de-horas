import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="ISOSED - Gestão de Banco 36h", layout="centered")
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÕES DE IMPOSTOS ---
def calcular_imposto_total(valor_bruto):
    inss = 0
    faixas_inss = [(1518.00, 0.075), (2800.00, 0.09), (4200.00, 0.12), (8157.00, 0.14)]
    anterior = 0
    for limite, aliquota in faixas_inss:
        if valor_bruto > limite:
            inss += (limite - anterior) * aliquota
            anterior = limite
        else:
            inss += (valor_bruto - anterior) * aliquota
            break
    
    base_irpf = valor_bruto - inss
    irpf = 0
    if base_irpf > 4664.68: irpf = (base_irpf * 0.275) - 893.66
    elif base_irpf > 3751.05: irpf = (base_irpf * 0.225) - 662.77
    elif base_irpf > 2826.65: irpf = (base_irpf * 0.15) - 381.44
    elif base_irpf > 2259.20: irpf = (base_irpf * 0.075) - 169.44
    return inss + max(0, irpf)

# --- FUNÇÕES DE DADOS ---
def buscar_dados(aba):
    return conn.read(worksheet=aba, ttl=0)

def salvar_dados(df_novo):
    conn.update(worksheet="Lancamentos", data=df_novo)
    st.cache_data.clear()

def calcular_horas_regra(data, entrada, saida, almoco, tipo="positivo"):
    t1 = datetime.combine(data, entrada); t2 = datetime.combine(data, saida)
    diff = (t2 - t1).total_seconds() / 3600
    if almoco: diff -= 1
    brutas = max(0, diff)
    
    if tipo == "positivo":
        if data.weekday() <= 4: # Semana: 1.25x com limite de 2h finais
            return min(brutas * 1.25, 2.0)
        elif data.weekday() == 5: # Sábado: 1.5x
            return brutas * 1.5
    return brutas

# --- LOGIN ---
if 'logado' not in st.session_state: st.session_state.logado = False
if not st.session_state.logado:
    st.title("🔐 Login ISOSED")
    with st.form("l"):
        u = st.text_input("Usuário").lower().strip()
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            df_u = buscar_dados("Usuarios")
            valid = df_u[(df_u['usuario'] == u) & (df_u['senha'].astype(str) == p)]
            if not valid.empty:
                st.session_state.logado, st.session_state.usuario = True, u
                st.session_state.nome = valid.iloc[0]['nome_exibicao']
                st.rerun()
            else: st.error("Acesso negado")
    st.stop()

# --- CARREGAMENTO E LOGICA DE LIMITE ---
v_hora = st.sidebar.number_input("Valor Hora (R$)", min_value=0.0, value=25.0)
salario_base = v_hora * 220

df_todos = buscar_dados("Lancamentos")
df_user = df_todos[df_todos['usuario'] == st.session_state.usuario]

# Cálculo de Cota (Soma de todos os créditos desde o último 'Zerar')
total_creditos_feitos = df_user[df_user['tipo'] == "Crédito"]['horas'].sum()
total_debitos_feitos = df_user[df_user['tipo'] == "Débito"]['horas'].sum()
saldo_atual = total_creditos_feitos - total_debitos_feitos
restante_na_cota = 36 - total_creditos_feitos

# --- INTERFACE ---
st.sidebar.write(f"👤 {st.session_state.nome}")
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()

st.title("Controle de Banco de Horas")
tab1, tab2, tab3 = st.tabs(["➕ Lançar Crédito", "➖ Lançar Folga", "📊 Extrato e Zerar"])

with tab1:
    st.info(f"Cota de Crédito Usada: **{total_creditos_feitos:.2f} / 36.00h**")
    if restante_na_cota <= 0:
        st.error("⚠️ Limite de 36h atingido! Zere o banco para novos lançamentos.")
    else:
        with st.form("f_c"):
            d = st.date_input("Data")
            c1, c2 = st.columns(2)
            ent = c1.time_input("Entrada", value=time(8,0), step=300)
            sai = c2.time_input("Saída", value=time(17,0), step=300)
            alm = st.checkbox("Almoço?", value=True)
            if st.form_submit_button("Registrar Crédito"):
                h = calcular_horas_regra(d, ent, sai, alm, "positivo")
                if h > restante_na_cota: h = restante_na_cota # Trava manual
                novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d.strftime("%d/%m/%Y"), 
                                      "entrada": ent.strftime("%H:%M"), "saida": sai.strftime("%H:%M"), 
                                      "tipo": "Crédito", "horas": h}])
                salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
                st.rerun()

with tab2:
    st.subheader("Registrar Folga ou Saída Cedo")
    modo = st.radio("Tipo:", ["Dia Inteiro", "Parcial"])
    with st.form("f_d"):
        d_n = st.date_input("Data da Folga")
        h_d, e_v, s_v = 0, "-", "-"
        if modo == "Parcial":
            c1, c2 = st.columns(2)
            e_n = c1.time_input("Início", value=time(8,0), step=300)
            s_n = c2.time_input("Fim", value=time(12,0), step=300)
            al_n = st.checkbox("Descontar Almoço?", value=False)
            e_v, s_v = e_n.strftime("%H:%M"), s_n.strftime("%H:%M")
        if st.form_submit_button("Confirmar Débito"):
            if modo == "Dia Inteiro":
                h_d = 9.0 if d_n.weekday() <= 3 else 8.0
                e_v, s_v = "Folga", "Integral"
            else: h_d = calcular_horas_regra(d_n, e_n, s_n, al_n, "negativo")
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d_n.strftime("%d/%m/%Y"), 
                                  "entrada": e_v, "saida": s_v, "tipo": "Débito", "horas": h_d}])
            salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

with tab3:
    # Financeiro (Baseado no total de créditos da cota)
    bruto_extras = total_creditos_feitos * (v_hora * 2.1) # 110%
    imp_base = calcular_imposto_total(salario_base)
    imp_total = calcular_imposto_total(salario_base + bruto_extras)
    liquido_extra = bruto_extras - (imp_total - imp_base)

    col1, col2 = st.columns(2)
    col1.metric("Saldo do Banco", f"{saldo_atual:.2f}h", delta="Negativo" if saldo_atual < 0 else "Crédito")
    col2.metric("Valor Líquido das Extras", f"R$ {liquido_extra:,.2f}")

    st.divider()
    if not df_user.empty:
        st.dataframe(df_user[["data", "entrada", "saida", "tipo", "horas"]], use_container_width=True)
        
        st.subheader("⚙️ Manutenção do Banco")
        if st.button("Zerar Banco de Horas (Reiniciar Cota)", type="primary"):
            # O zerar agora limpa o histórico para resetar a cota de 36h
            # Salvamos apenas os dados de OUTROS usuários
            df_limpo = df_todos[df_todos['usuario'] != st.session_state.usuario]
            salvar_dados(df_limpo)
            st.success("Banco reiniciado! Cota de 36h liberada.")
            st.rerun()
        
        st.divider()
        ops = {f"{r['data']} | {r['tipo']} | {r['horas']:.2f}h": i for i, r in df_user.iterrows()}
        sel = st.selectbox("Apagar registro específico:", options=list(ops.keys()))
        if st.button("Remover Registro"):
            salvar_dados(df_todos.drop(ops[sel]))
            st.rerun()
