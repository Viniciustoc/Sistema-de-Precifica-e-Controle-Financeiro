# Passo 1: Importações e Configuração do App
import sqlite3
import os
from flask import Flask, render_template, request, redirect, flash, g, url_for
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json

# --- Configuração do Aplicativo ---
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "uma-chave-secreta-padrao-para-desenvolvimento")
DATABASE = "doceria.db"
ADMIN_PASSWORD = "@Vinicius13"


# Passo 2: Gerenciamento da Conexão com o DataBase
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


# Passo 3: Inicialização do Database
def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        # Tabelas de Custo
        cursor.execute('''CREATE TABLE IF NOT EXISTS ingredientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE NOT NULL, preco_embalagem REAL NOT NULL,
            quant_embalagem REAL NOT NULL, densidade REAL DEFAULT 1.0 )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS receitas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE NOT NULL, descricao TEXT,
            rendimento INTEGER NOT NULL DEFAULT 1 )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS receita_ingredientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, receita_id INTEGER NOT NULL, ingrediente_id INTEGER NOT NULL,
            quantidade REAL NOT NULL, unidade TEXT NOT NULL,
            FOREIGN KEY (receita_id) REFERENCES receitas (id) ON DELETE CASCADE,
            FOREIGN KEY (ingrediente_id) REFERENCES ingredientes (id) ON DELETE CASCADE )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS custos_adicionais (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE NOT NULL, tipo TEXT NOT NULL,
            custo_unitario REAL NOT NULL, unidade_medida TEXT, vida_util INTEGER, descricao TEXT )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS receita_custos_adicionais (
            id INTEGER PRIMARY KEY AUTOINCREMENT, receita_id INTEGER NOT NULL, custo_adicional_id INTEGER NOT NULL,
            quantidade_utilizada REAL NOT NULL,
            FOREIGN KEY (receita_id) REFERENCES receitas (id) ON DELETE CASCADE,
            FOREIGN KEY (custo_adicional_id) REFERENCES custos_adicionais (id) ON DELETE CASCADE )''')

        # Tabelas Financeiras
        cursor.execute('''CREATE TABLE IF NOT EXISTS despesas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            descricao TEXT NOT NULL, 
            valor REAL NOT NULL,
            data DATE NOT NULL, categoria TEXT )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS vendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data DATE NOT NULL, total_venda REAL NOT NULL, metodo_pagamento TEXT )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL,
            preco_venda REAL NOT NULL
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS produto_composicao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            receita_id INTEGER NOT NULL,
            fracao_receita REAL NOT NULL,
            FOREIGN KEY (produto_id) REFERENCES produtos (id) ON DELETE CASCADE,
            FOREIGN KEY (receita_id) REFERENCES receitas (id) ON DELETE CASCADE
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS venda_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT, venda_id INTEGER NOT NULL, produto_id INTEGER,
            quantidade INTEGER NOT NULL, preco_unitario_venda REAL NOT NULL, custo_unitario_producao REAL NOT NULL,
            FOREIGN KEY (venda_id) REFERENCES vendas (id) ON DELETE CASCADE,
            FOREIGN KEY (produto_id) REFERENCES produtos (id) ON DELETE SET NULL )''')

        db.commit()
        print("Banco de dados inicializado com sucesso!")


# Passo 4: Funções de acesso ao DATABASE (DAO)

# --- Seção Ingredientes ---
def get_ingrediente(nome):
    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM ingredientes WHERE nome = ?", (nome,))
    return cursor.fetchone()


def get_todos_ingredientes():
    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM ingredientes ORDER BY nome")
    return cursor.fetchall()


def is_ingrediente_em_uso(ingrediente_id):
    cursor = get_db().cursor()
    cursor.execute("SELECT 1 FROM receita_ingredientes WHERE ingrediente_id = ?", (ingrediente_id,))
    return cursor.fetchone() is not None


def delete_ingrediente_db(ingrediente_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM ingredientes WHERE id = ?", (ingrediente_id,))
    db.commit()


def get_ingrediente_by_id(id):
    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM ingredientes WHERE id = ?", (id,))
    return cursor.fetchone()


def add_ingrediente(nome, preco, quantidade, densidade=1.0):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO ingredientes (nome, preco_embalagem, quant_embalagem, densidade) VALUES(?,?,?,?)",
        (nome, preco, quantidade, densidade))
    db.commit()


# --- Seção Receitas ---
def get_receitas():
    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM receitas ORDER BY nome")
    return cursor.fetchall()


def get_receita(receita_id):
    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM receitas WHERE id = ?", (receita_id,))
    return cursor.fetchone()


def add_receita(nome, descricao, rendimento):
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("INSERT INTO receitas (nome, descricao, rendimento) VALUES(?,?,?)",
                       (nome, descricao, rendimento))
        db.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def update_receita(receita_id, novo_nome, nova_descricao, novo_rendimento):
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE receitas SET nome = ?, descricao = ?, rendimento = ? WHERE id = ?",
                       (novo_nome, nova_descricao, novo_rendimento, receita_id))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def delete_receita(receita_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM receitas WHERE id = ?", (receita_id,))
    db.commit()


# --- Seção Relação Receitas <--> Ingredientes ---
def get_ingredientes_receita(receita_id):
    cursor = get_db().cursor()
    cursor.execute(
        '''
        SELECT ri.id, i.nome, ri.quantidade, ri.unidade, i.densidade, i.preco_embalagem, i.quant_embalagem
        FROM receita_ingredientes ri
        JOIN ingredientes i ON ri.ingrediente_id = i.id
        WHERE ri.receita_id = ?
        ''', (receita_id,))
    return cursor.fetchall()


def add_ingrediente_receita(receita_id, ingrediente_id, quantidade, unidade):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO receita_ingredientes (receita_id, ingrediente_id, quantidade, unidade) VALUES(?,?,?,?)",
        (receita_id, ingrediente_id, quantidade, unidade))
    db.commit()


def get_ingrediente_receita_by_id(ingrediente_receita_id):
    cursor = get_db().cursor()
    cursor.execute(
        '''
        SELECT ri.*, i.nome
        FROM receita_ingredientes ri
        JOIN ingredientes i ON ri.ingrediente_id = i.id
        WHERE ri.id = ?
        ''', (ingrediente_receita_id,))
    return cursor.fetchone()


def update_ingrediente_receita(ingrediente_receita_id, nova_quantidade, nova_unidade):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('UPDATE receita_ingredientes SET quantidade = ?, unidade = ? WHERE id = ?',
                   (nova_quantidade, nova_unidade, ingrediente_receita_id))
    db.commit()


def delete_ingrediente_receita(ingrediente_receita_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('DELETE FROM receita_ingredientes WHERE id = ?', (ingrediente_receita_id,))
    db.commit()


# --- Seção Custos Adicionais ---
def get_custos_adicionais():
    cursor = get_db().cursor()
    cursor.execute('SELECT * FROM custos_adicionais ORDER BY tipo, nome')
    return cursor.fetchall()


def get_custo_adicional_by_id(custo_id):
    cursor = get_db().cursor()
    cursor.execute('SELECT * FROM custos_adicionais WHERE id = ?', (custo_id,))
    return cursor.fetchone()


def add_custo_adicional(nome, tipo, custo_unitario, unidade_medida, vida_util, descricao):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''INSERT INTO custos_adicionais
        (nome,tipo,custo_unitario,unidade_medida,vida_util, descricao)
            VALUES(?,?,?,?,?,?)''',
                   (nome, tipo, custo_unitario, unidade_medida, vida_util, descricao))
    db.commit()


def update_custo_adicional(custo_id, nome, tipo, custo_unitario, unidade_medida, vida_util, descricao):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(''' UPDATE custos_adicionais
                            SET nome = ?, tipo = ?, custo_unitario = ?, unidade_medida = ?, vida_util = ?, descricao = ?
                            WHERE id = ?''',
                   (nome, tipo, custo_unitario, unidade_medida, vida_util, descricao, custo_id))
    db.commit()


def delete_custo_adicional(custos_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('DELETE FROM custos_adicionais WHERE id = ?', (custos_id,))
    db.commit()


# --- Seção Relação Receita <--> Custos Adicionais ---
def get_custos_adicionais_receita(receita_id):
    cursor = get_db().cursor()
    cursor.execute('''SELECT rca.id, ca.nome, ca.tipo, rca.quantidade_utilizada,
                    ca.custo_unitario, ca.unidade_medida, ca.vida_util, ca.descricao
                    FROM receita_custos_adicionais rca
                    JOIN custos_adicionais ca ON rca.custo_adicional_id = ca.id
                    WHERE rca.receita_id = ?''', (receita_id,))
    return cursor.fetchall()


def add_custo_adicional_receita(receita_id, custo_id, quantidade):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''INSERT INTO receita_custos_adicionais
                        (receita_id, custo_adicional_id, quantidade_utilizada)
                        VALUES(?,?,?)''',
                   (receita_id, custo_id, quantidade))
    db.commit()


def delete_custo_adicional_receita(custo_receita_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''DELETE FROM receita_custos_adicionais WHERE id = ?''', (custo_receita_id,))
    db.commit()

def get_custo_adicional_receita_by_id(custo_receita_id):
    cursor = get_db().cursor()
    cursor.execute('SELECT * FROM receita_custos_adicionais WHERE id = ?', (custo_receita_id,))
    return cursor.fetchone()

# --- Seção de Produtos ---
def get_produtos():
    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM produtos ORDER BY nome")
    return cursor.fetchall()


def get_produto_by_id(produto_id):
    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,))
    return cursor.fetchone()


def add_produto(nome, preco_venda, composicao):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("INSERT INTO produtos (nome, preco_venda) VALUES (?, ?)", (nome, preco_venda))
        produto_id = cursor.lastrowid
        for item in composicao:
            receita_id = item['receita_id']
            fracao = item['fracao']
            cursor.execute("INSERT INTO produto_composicao (produto_id, receita_id, fracao_receita) VALUES (?, ?, ?)",
                           (produto_id, receita_id, fracao))
        db.commit()
        return produto_id
    except sqlite3.IntegrityError:
        db.rollback()
        return None


def delete_produto(produto_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))
    db.commit()


# --- Funções de Lógica de Negócio ---
def converter_para_gramas(quantidade, unidade, densidade=1.0):
    fatores_conversao = {
        'g': 1.0, 'kg': 1000.0, 'ml': 1.0, 'l': 1000.0,
        'colher': 15.0, 'xícara': 240.0, 'unidade': 50.0, 'pitada': 0.5,
    }
    unidades_de_volume = ['ml', 'l', 'colher', 'xícara']
    fator = fatores_conversao.get(unidade, 1.0)
    if unidade in unidades_de_volume:
        return quantidade * fator * (densidade or 1.0)
    return quantidade * fator


def calcular_custo_ingrediente(preco_embalagem, quant_embalagem, qtd_convertida_gramas):
    if quant_embalagem > 0:
        return (preco_embalagem / quant_embalagem) * qtd_convertida_gramas
    return 0


def calcular_custo_adicional_total(receita_id):
    total = 0
    custos_na_receita = get_custos_adicionais_receita(receita_id)
    for custo in custos_na_receita:
        custo_unitario = custo['custo_unitario']
        vida_util = custo['vida_util']
        if vida_util and vida_util > 0:
            total += (custo_unitario / vida_util) * custo['quantidade_utilizada']
        else:
            total += custo_unitario * custo['quantidade_utilizada']
    return total


def calcular_custo_total_receita(receita_id):
    ingredientes = get_ingredientes_receita(receita_id)
    custo_ingredientes = 0
    for ingr in ingredientes:
        qtd_gramas = converter_para_gramas(ingr['quantidade'], ingr['unidade'], ingr['densidade'])
        custo_ingredientes += calcular_custo_ingrediente(ingr['preco_embalagem'], ingr['quant_embalagem'], qtd_gramas)
    custo_adicionais = calcular_custo_adicional_total(receita_id)
    return custo_ingredientes + custo_adicionais


def calcular_custo_produto(produto_id):
    db = get_db()
    cursor = db.cursor()

    # 1. Modificamos a query para buscar também o 'rendimento' da receita
    cursor.execute("""
        SELECT pc.fracao_receita, r.id as receita_id, r.rendimento
        FROM produto_composicao pc
        JOIN receitas r ON pc.receita_id = r.id
        WHERE pc.produto_id = ?
    """, (produto_id,))

    composicao = cursor.fetchall()
    custo_total_produto = 0

    for item in composicao:
        # 2. Get cost of the ENTIRE batch (e.g., R$ 100)
        custo_total_da_receita = calcular_custo_total_receita(item['receita_id'])

        # 3. Get the yield of the batch (e.g., 30 units)
        rendimento_receita = item['rendimento']

        # 4. (Segurança) Evita divisão por zero se o rendimento for 0 ou Nulo
        if not rendimento_receita or rendimento_receita <= 0:
            rendimento_receita = 1

            # 5. ESTA É A MUDANÇA: Calcula o custo POR UNIDADE
        # (e.g., R$ 100 / 30 units = R$ 3.33 per unit)
        custo_unitario_da_receita = custo_total_da_receita / rendimento_receita

        # 6. Get the quantity of units used in this product (e.g., 1 unit)
        # (Assumindo que 'fracao_receita' é usado como 'quantidade')
        quantidade_utilizada = item['fracao_receita']

        # 7. Add to total cost (e.g., R$ 3.33 * 1 unit)
        custo_total_produto += custo_unitario_da_receita * quantidade_utilizada

    return custo_total_produto


@app.context_processor
def utility_processor():
    return dict(
        calcular_custo_total_receita=calcular_custo_total_receita,
        calcular_custo_produto=calcular_custo_produto
    )


# --- Funções do Módulo Financeiro ---
def add_despesa(descricao, valor, data, categoria):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO despesas (descricao, valor, data, categoria) VALUES(?,?,?,?)",
                   (descricao, valor, data, categoria))
    db.commit()


def add_venda(venda_itens, data, metodo_pagamento):
    db = get_db()
    cursor = db.cursor()
    total_venda = sum(item['quantidade'] * item['preco_venda'] for item in venda_itens)
    cursor.execute("INSERT INTO vendas (data, total_venda, metodo_pagamento) VALUES(?,?,?)",
                   (data, total_venda, metodo_pagamento))
    venda_id = cursor.lastrowid
    for item in venda_itens:
        cursor.execute(
            """INSERT INTO venda_itens
            (venda_id, produto_id, quantidade, preco_unitario_venda, custo_unitario_producao)
            VALUES(?,?,?,?,?)""",
            (venda_id, item['produto_id'], item['quantidade'], item['preco_venda'], item['custo_producao']))
    db.commit()


def calcular_crescimento(atual, anterior):
    """Helper para calcular o crescimento percentual com segurança"""
    if anterior is None or anterior == 0:
        return None
    try:
        return (atual - anterior) / abs(anterior)
    except TypeError:
        return None


def get_dados_financeiros():
    """Busca TODOS os dados financeiros do banco sem filtro de data, os filtros sao aplicados no Pandas"""
    db = get_db()
    # parse_dates conver a coluna data para datetime
    vendas_df = pd.read_sql_query("SELECT * FROM vendas", db, parse_dates=['data'])
    venda_itens_df = pd.read_sql_query("SELECT * FROM venda_itens", db)
    despesas_df = pd.read_sql_query("SELECT * FROM despesas", db, parse_dates=['data'])
    produtos_df = pd.read_sql_query("SELECT id, nome FROM produtos", db)

    # Pré calcula colunas de lucro e venda por item (para os graficos Top/Bottom)
    if not venda_itens_df.empty:
        # CORREÇÃO 1: 'custo_unitario_producao'
        venda_itens_df['lucro_bruto_item'] = (venda_itens_df['preco_unitario_venda'] - venda_itens_df[
            'custo_unitario_producao']) * venda_itens_df['quantidade']
        venda_itens_df['total_venda_item'] = venda_itens_df['preco_unitario_venda'] * venda_itens_df['quantidade']
    else:
        # Garante que as colunas existam mesmo sem valores
        venda_itens_df['lucro_bruto_item'] = pd.Series(dtype='float')
        venda_itens_df['total_venda_item'] = pd.Series(dtype='float')
    return vendas_df, venda_itens_df, despesas_df, produtos_df

def get_despesas_recentes(limite=20):
    """Busca as N despesas mais recentes."""
    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM despesas ORDER BY data DESC, id DESC LIMIT ?", (limite,))
    return cursor.fetchall()

def delete_despesa(despesa_id):
    """Exclui uma despesa específica do banco."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM despesas WHERE id = ?", (despesa_id,))
    db.commit()

def get_vendas_recentes(limite=20):
    """Busca as N vendas mais recentes."""
    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM vendas ORDER BY data DESC, id DESC LIMIT ?", (limite,))
    return cursor.fetchall()

def delete_venda(venda_id):
    """Exclui uma venda específica do banco.
    O 'ON DELETE CASCADE' na tabela venda_itens cuidará dos itens.
    """
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM vendas WHERE id = ?", (venda_id,))
    db.commit()


@app.route("/financeiro/dashboard")
def dashboard_financeiro():
    # 1. Obter e Tratar Datas do Filtro
    data_inicio_str = request.args.get('start_date')
    data_fim_str = request.args.get('end_date')

    # Define datas padrao(ultimos 90 dias) se nenhum filtro for aplicado
    if not data_fim_str:
        data_fim = datetime.now()
    else:
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d')
    if not data_inicio_str:
        data_inicio = data_fim - timedelta(days=90)
    else:
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d')

    # Converte para date para comparações seguras com pandas
    data_inicio_filtro = data_inicio.date()
    data_fim_filtro = data_fim.date()

    # 2. Obter Todos os dados do DB
    vendas_df, vendas_itens_df, despesas_df, produtos_df = get_dados_financeiros()

    # 3. Calcular Periodos Anteriores para KPIs de Crescimento

    # Periodo Semana Anterior (7 dias antes do inicio do filtro)
    data_fim_sem_ant = data_inicio_filtro - timedelta(days=1)
    # CORREÇÃO 2: Lógica de data
    data_inicio_sem_ant = data_fim_sem_ant - timedelta(days=6)  # 7 dias de periodo

    # Periodo Mês Anterior (30 dias antes do inicio do filtro)
    data_fim_mes_ant = data_inicio_filtro - timedelta(days=1)
    # CORREÇÃO 3: Lógica de data
    data_inicio_mes_ant = data_fim_mes_ant - timedelta(days=29)  # 30 dias de periodo

    # 4. Função Helper Interna para Calcular KPIs por Periodo
    def calcular_kpis_periodo(df_v, df_i, df_d, inicio, fim):
        # Filtra os dataframes por periodo de data
        vendas_periodo = df_v[
            (df_v['data'].dt.date >= inicio) & (df_v['data'].dt.date <= fim)
            ].copy()
        despesas_periodo = df_d[
            (df_d['data'].dt.date >= inicio) & (df_d['data'].dt.date <= fim)
            ].copy()

        itens_periodo = df_i[df_i['venda_id'].isin(vendas_periodo['id'])]

        # Calcular KPIs
        total_vendido = vendas_periodo['total_venda'].sum()
        total_gasto = despesas_periodo['valor'].sum()
        lucro_liquido = total_vendido - total_gasto
        total_quantidade = itens_periodo['quantidade'].sum()

        return {
            'total_vendido': total_vendido,
            'total_gasto': total_gasto,
            'lucro_liquido': lucro_liquido,
            'total_quantidade': total_quantidade,
        }

    # --- Fim da Função Helper ---

    # 5. Calcular KPIs para os 3 periodos
    kpis_atual = calcular_kpis_periodo(vendas_df, vendas_itens_df, despesas_df, data_inicio_filtro, data_fim_filtro)
    # CORREÇÃO 4: Datas corretas
    kpis_sem_ant = calcular_kpis_periodo(vendas_df, vendas_itens_df, despesas_df, data_inicio_sem_ant, data_fim_sem_ant)
    # CORREÇÃO 5: Datas corretas
    kpis_mes_ant = calcular_kpis_periodo(vendas_df, vendas_itens_df, despesas_df, data_inicio_mes_ant, data_fim_mes_ant)

    # 6. Calcular Crescimento %
    cresc_semana = calcular_crescimento(kpis_atual['lucro_liquido'], kpis_sem_ant['lucro_liquido'])
    # CORREÇÃO 6: Função correta
    cresc_mes = calcular_crescimento(kpis_atual['lucro_liquido'], kpis_mes_ant['lucro_liquido'])

    # 7. Prepara Dados para graficos (usando dados do periodo atual)

    # Re-filtrar os DFs do periodo atual
    vendas_atuais = vendas_df[
        (vendas_df['data'].dt.date >= data_inicio_filtro) & (vendas_df['data'].dt.date <= data_fim_filtro)
        ].copy()  # <--- CORREÇÃO 7: Parênteses
    despesas_atuais = despesas_df[
        (despesas_df['data'].dt.date >= data_inicio_filtro) & (despesas_df['data'].dt.date <= data_fim_filtro)
        ].copy()
    # CORREÇÃO 8: DataFrame correto
    itens_atuais = vendas_itens_df[vendas_itens_df['venda_id'].isin(vendas_atuais['id'])].copy()

    # Merge de itens com produtos para pegar os Nomes
    if not itens_atuais.empty and not produtos_df.empty:
        itens_com_produtos = pd.merge(itens_atuais, produtos_df, left_on='produto_id', right_on='id', how='left')
    else:
        # Cria DF vazio com colunas necessarias se nao houver dados
        itens_com_produtos = pd.DataFrame(columns=['nome', 'quantidade', 'lucro_bruto_item', 'total_venda_item'])

    # --- Grafico 1 & 2 Evolução Semanal ---
    # Resample Vendas por Semana (W-Mon = Inicios da Semana na Segunda)
    vendas_semanais = vendas_atuais.set_index('data').resample('W-Mon', label='left', closed='left')[
        'total_venda'].sum().reset_index()
    # CORREÇÃO 9: 'closed' consistente
    despesas_semanais = despesas_atuais.set_index('data').resample('W-Mon', label='left', closed='left')[
        'valor'].sum().reset_index()

    # Juntar dados semanais
    evolucao_df = pd.merge(vendas_semanais, despesas_semanais, on='data', how='outer').fillna(0)
    evolucao_df['lucro_liquido'] = evolucao_df['total_venda'] - evolucao_df['valor']

    # Grafico 1: Lucro Bruto Liquido e Venda (linha)
    fig_evolucao_lucro_venda = go.Figure()
    fig_evolucao_lucro_venda.add_trace(
        go.Scatter(x=evolucao_df['data'], y=evolucao_df['lucro_liquido'], mode='lines+markers',  name='Lucro Líquido (Venda-Despesa)', hovertemplate= '<b>Semana de:</b> %{x|%d/%m/%Y}<br>' + '<b>Lucro Líquido:</b> R$ %{y:,.2f}<extra></extra>'))
    fig_evolucao_lucro_venda.add_trace(go.Scatter(x=evolucao_df['data'], y=evolucao_df['total_venda'], mode='lines+markers', name='Total Vendido', hovertemplate = '<b>Semana de:</b> %{x|%d/%m/%Y}<br>' +'<b>Total Vendido:</b> R$ %{y:,.2f}<extra></extra>'))
    fig_evolucao_lucro_venda.update_layout(title='Evolução Semanal: Lucro Liquido vs Vendas', xaxis_title='Semana', yaxis_title = 'Valor (R$)', hovermode="x unified")
    graph_evolucao_lucro_venda_html = fig_evolucao_lucro_venda.to_html(full_html=False, include_plotlyjs='cdn')

    # Grafico 2: Lucro Liquido e Venda (Linha)
    fig_evolucao_gastos = px.line(evolucao_df, x='data', y='valor', title='Evolução Gastos Semanais', markers=True)
    fig_evolucao_gastos.update_traces(
        hovertemplate='<b>Semana de:</b> %{x|%d/%m/%Y}<br>' +
                      '<b>Gastos:</b> R$ %{y:,.2f}<extra></extra>'
    )
    fig_evolucao_gastos.update_layout(
        yaxis_title='Valor (R$)'
    )
    graph_evolucao_gastos_html = fig_evolucao_gastos.to_html(full_html=False, include_plotlyjs='cdn')
    # Grafico 3, 4, 5 : Top Bottom
    # Agrupa todos os itens vendidos por nome do produto
    produtos_agrupados = itens_com_produtos.groupby('nome').agg(
        total_vendido = ('total_venda_item', 'sum'),
        total_lucro_bruto = ('lucro_bruto_item', 'sum'),
        total_quantidade = ('quantidade', 'sum')
    ).reset_index()
    produtos_agrupados['total_vendido'] = pd.to_numeric(produtos_agrupados['total_vendido'])
    produtos_agrupados['total_lucro_bruto'] = pd.to_numeric(produtos_agrupados['total_lucro_bruto'])
    produtos_agrupados['total_quantidade'] = pd.to_numeric(produtos_agrupados['total_quantidade'])

    #Grafico 3: Top/ Bottom 5 Valor Vendido
    top5_vendido = produtos_agrupados.nlargest(5, 'total_vendido')
    bottom5_vendido = produtos_agrupados.nsmallest(5, 'total_vendido')
    fig_top_bottom_vendido = px.bar(pd.concat([top5_vendido, bottom5_vendido]), x = 'nome', y = 'total_vendido', title = 'Top/Bottom 5 Produtos por Valor Vendido')
    graph_top_bottom_vendido_html = fig_top_bottom_vendido.to_html(full_html=False, include_plotlyjs='cdn')

    # Grafico 4: Top / Bottom 5 Lucro Bruto
    top5_lucro = produtos_agrupados.nlargest(5,'total_lucro_bruto')
    bottom5_lucro = produtos_agrupados.nsmallest(5, 'total_lucro_bruto')
    fig_top_bottom_lucro_bruto = px.bar(pd.concat([top5_lucro, bottom5_lucro]), x='nome', y="total_lucro_bruto", title="Top/Bottoms 5 Produtos por Lucro Bruto")
    graph_top_bottom_lucro_html = fig_top_bottom_lucro_bruto.to_html(full_html=False, include_plotlyjs='cdn')

    # Grafico 5: Top / Bottom 5 Quantidade Vendida
    top5_quantidade = produtos_agrupados.nlargest(5,"total_quantidade")
    bottom5_quantidade = produtos_agrupados.nsmallest(5, 'total_quantidade')
    fig_top_bottom_quantidade = px.bar(pd.concat([top5_quantidade, bottom5_quantidade]), x= 'nome', y='total_quantidade', title="Top/Bottom 5 Produtos por Quantidade Vendida")
    graph_top_bottom_qtd_html = fig_top_bottom_quantidade.to_html(full_html=False, include_plotlyjs='cdn')

    # --- 8. Enviar tudo para o Template ---
    return render_template('dashboard.html',
                           # KPIs
                           kpis=kpis_atual,
                           cresc_semana=cresc_semana,
                           cresc_mes=cresc_mes,
                           # Gráficos
                           graph_evolucao_lucro_venda_html=graph_evolucao_lucro_venda_html,
                           graph_evolucao_gastos_html=graph_evolucao_gastos_html,
                           graph_top_bottom_vendido_html=graph_top_bottom_vendido_html,
                           graph_top_bottom_lucro_html=graph_top_bottom_lucro_html,
                           graph_top_bottom_qtd_html=graph_top_bottom_qtd_html,
                           # Filtros (para preencher os campos de data)
                           data_inicio=data_inicio_filtro.strftime('%Y-%m-%d'),
                           data_fim=data_fim_filtro.strftime('%Y-%m-%d')
                           )

# --- Rotas da Aplicação (Views) ---

@app.route("/")
def index():
    return render_template('index.html')


@app.route("/receitas")
def gerir_receitas():
    receitas = get_receitas()
    return render_template('gerir_receitas.html', receitas=receitas)


@app.route("/criar_receita", methods=["GET", "POST"])
def criar_receita():
    if request.method == "POST":
        nome_receita = request.form["nome_receita"].strip()
        descricao = request.form["descricao"].strip()
        try:
            rendimento = int(request.form.get("rendimento", 1))
            if rendimento <= 0: rendimento = 1
        except (ValueError, TypeError):
            rendimento = 1
        if not nome_receita:
            flash("O nome da receita nao pode estar vazio!", "error")
            return render_template("criar_receita.html", nome_receita=nome_receita, descricao=descricao)
        receita_id = add_receita(nome_receita, descricao, rendimento)
        if receita_id is None:
            flash(f"Ja existe uma receita com o nome '{nome_receita}'.", "error")
            return render_template("criar_receita.html", nome_receita=nome_receita, descricao=descricao)
        flash(f"Receita '{nome_receita}' criada com sucesso!", "success")
        return redirect(url_for("adicionar_ingredientes", receita_id=receita_id))
    return render_template("criar_receita.html")


@app.route("/editar_receita/<int:receita_id>", methods=["GET", "POST"])
def editar_receita(receita_id):
    receita = get_receita(receita_id)
    if not receita:
        flash("Receita não encontrada!", "error")
        return redirect(url_for("gerir_receitas"))
    if request.method == "POST":
        novo_nome = request.form["nome_receita"].strip()
        nova_descricao = request.form["descricao"].strip()
        try:
            novo_rendimento = int(request.form.get("rendimento", 1))
            if novo_rendimento <= 0: novo_rendimento = 1
        except (ValueError, TypeError):
            novo_rendimento = 1
        if not novo_nome:
            flash("O nome da receita não pode estar vazio!", "error")
            return render_template("editar_receita.html", receita=receita)
        if update_receita(receita_id, novo_nome, nova_descricao, novo_rendimento):
            flash(f"Receita '{novo_nome}' atualizada com sucesso!", "success")
            return redirect(url_for("gerir_receitas"))
        else:
            flash(f"Já existe uma receita com o nome '{novo_nome}'.", "error")
            receita_editada = {'id': receita_id, 'nome': novo_nome, 'descricao': nova_descricao,
                               'rendimento': novo_rendimento}
            return render_template("editar_receita.html", receita=receita_editada)
    return render_template("editar_receita.html", receita=receita)


@app.route("/receitas/excluir/<int:receita_id>", methods=["POST"])
def excluir_receita(receita_id):
    receita = get_receita(receita_id)
    if receita:
        delete_receita(receita_id)
        flash(f"Receita '{receita['nome']}' excluída com sucesso!", "success")
    else:
        flash("Receita não encontrada!", "error")
    return redirect(url_for("gerir_receitas"))


@app.route("/receita/<int:receita_id>")
def ver_receita(receita_id):
    receita = get_receita(receita_id)
    if not receita:
        flash("Receita não encontrada!", "error")
        return redirect(url_for("gerir_receitas"))

    # 1. Obter ingredientes e calcular o custo de CADA UM (necessário para a lista no HTML)
    ingredientes_db = get_ingredientes_receita(receita_id)
    ingredientes_com_custo = []
    custo_ingredientes_total = 0

    for ingr in ingredientes_db:
        # Reutiliza suas funções de cálculo
        qtd_gramas = converter_para_gramas(ingr['quantidade'], ingr['unidade'], ingr['densidade'])
        custo_item = calcular_custo_ingrediente(ingr['preco_embalagem'], ingr['quant_embalagem'], qtd_gramas)

        # Converte a linha do DB (sqlite3.Row) para um dicionário para podermos adicionar a chave 'custo'
        ingr_dict = dict(ingr)
        ingr_dict['custo'] = custo_item
        ingredientes_com_custo.append(ingr_dict)

        # Soma o custo total dos ingredientes
        custo_ingredientes_total += custo_item

    # 2. Obter custos adicionais (a lista)
    custos_adicionais_db = get_custos_adicionais_receita(receita_id)

    # 3. Calcular o total dos custos adicionais (usando sua função que já existe)
    custo_adicional_total = calcular_custo_adicional_total(receita_id)

    # 4. Calcular o Custo Total da Receita
    custo_total = custo_ingredientes_total + custo_adicional_total


    rendimento = receita['rendimento']

    # Garante que o rendimento (que vem do DB) não é Nulo ou 0
    if not rendimento or rendimento == 0:
        rendimento = 1  # Evita erro de divisão por zero

    custo_unitario = custo_total / rendimento
    # ==============================================

    # 5. Enviar tudo para o template
    return render_template("ver_receita.html",
                           receita=receita,
                           ingredientes=ingredientes_com_custo,
                           custos_adicionais=custos_adicionais_db,
                           custo_ingredientes=custo_ingredientes_total,
                           custo_adicional_total=custo_adicional_total,
                           custo_total=custo_total,
                           custo_unitario=custo_unitario)  # <-- Nova variável enviada

@app.route("/adicionar_ingredientes/<int:receita_id>", methods=["GET", "POST"])
def adicionar_ingredientes(receita_id):
    receita = get_receita(receita_id)
    if not receita:
        flash("Receita não encontrada!", "error")
        return redirect(url_for("gerir_receitas"))
    if request.method == "POST":
        nome_ingrediente = request.form["nome_ingrediente"].lower().strip()
        try:
            quantidade = float(request.form["quantidade"])
        except ValueError:
            flash("A quantidade deve ser um número.", "error")
            return redirect(url_for("adicionar_ingredientes", receita_id=receita_id))
        unidade = request.form["unidade"]
        ingrediente_cadastrado = get_ingrediente(nome_ingrediente)
        if not ingrediente_cadastrado:
            return redirect(url_for("novo_ingrediente", nome=nome_ingrediente, receita_id=receita_id,
                                    quantidade_original=quantidade, unidade_original=unidade))
        add_ingrediente_receita(receita_id, ingrediente_cadastrado['id'], quantidade, unidade)
        flash(f"Ingrediente '{nome_ingrediente}' adicionado à receita!", "success")
        return redirect(url_for("adicionar_ingredientes", receita_id=receita_id))
    ingredientes_db = get_ingredientes_receita(receita_id)
    custo_total = calcular_custo_total_receita(receita_id)
    return render_template("adicionar_ingredientes.html",
                           receita=receita,
                           ingredientes=ingredientes_db,
                           custo_total=custo_total)


@app.route("/novo_ingrediente", methods=["GET", "POST"])
def novo_ingrediente():
    if request.method == "POST":
        nome = request.form["nome"].lower().strip()
        try:
            preco = float(request.form["preco_embalagem"])
            quantidade_embalagem = float(request.form["quant_embalagem"])
            densidade = float(request.form.get("densidade", 1.0))
        except (ValueError, KeyError):
            flash("Preço, quantidade e densidade devem ser números.", "error")
            return render_template("novo_ingrediente.html", **request.form)

        existente = get_ingrediente(nome)
        if existente:
            flash(f"Ingrediente '{nome}' já existe.", "error")
        else:
            add_ingrediente(nome, preco, quantidade_embalagem, densidade)
            flash(f"Ingrediente '{nome}' cadastrado com sucesso!", "success")

        receita_id = request.form.get("receita_id")
        if receita_id and receita_id.isdigit():
            quantidade_original = request.form.get("quantidade_original")
            unidade_original = request.form.get("unidade_original")
            ingrediente = get_ingrediente(nome)
            if ingrediente:
                add_ingrediente_receita(int(receita_id), ingrediente['id'], float(quantidade_original),
                                        unidade_original)
                flash(f"Ingrediente '{nome}' adicionado à receita!", "success")
            return redirect(url_for("adicionar_ingredientes", receita_id=receita_id))

        return redirect(url_for("gerir_ingredientes"))

    return render_template("novo_ingrediente.html",
                           nome=request.args.get("nome", ""),
                           receita_id=request.args.get("receita_id"),
                           quantidade_original=request.args.get("quantidade_original"),
                           unidade_original=request.args.get("unidade_original"))


@app.route("/editar_ingrediente/<int:ingrediente_receita_id>", methods=["GET", "POST"])
def editar_ingrediente(ingrediente_receita_id):
    ingrediente_receita = get_ingrediente_receita_by_id(ingrediente_receita_id)
    if not ingrediente_receita:
        flash("Ingrediente da receita não encontrado!", "error")
        return redirect(url_for("gerir_receitas"))
    receita = get_receita(ingrediente_receita['receita_id'])
    if request.method == "POST":
        try:
            nova_quantidade = float(request.form["quantidade"])
        except ValueError:
            flash("A quantidade deve ser um número.", "error")
            return redirect(url_for("editar_ingrediente", ingrediente_receita_id=ingrediente_receita_id))
        nova_unidade = request.form["unidade"]
        update_ingrediente_receita(ingrediente_receita_id, nova_quantidade, nova_unidade)
        flash("Ingrediente atualizado com sucesso!", "success")
        return redirect(url_for("adicionar_ingredientes", receita_id=receita['id']))
    return render_template("editar_ingrediente.html",
                           receita=receita,
                           ingrediente=ingrediente_receita)


@app.route("/excluir_ingrediente/<int:ingrediente_receita_id>", methods=["POST"])
def excluir_ingrediente(ingrediente_receita_id):
    ingrediente_receita = get_ingrediente_receita_by_id(ingrediente_receita_id)
    if ingrediente_receita:
        receita_id = ingrediente_receita['receita_id']
        delete_ingrediente_receita(ingrediente_receita_id)
        flash("Ingrediente removido da receita!", "success")
        return redirect(url_for("adicionar_ingredientes", receita_id=receita_id))
    flash("Ingrediente da receita não encontrado!", "error")
    return redirect(url_for("gerir_receitas"))


# --- Rotas de Gestão de Ingredientes ---
@app.route("/ingredientes")
def gerir_ingredientes():
    todos_ingredientes = get_todos_ingredientes()
    return render_template('gerir_ingredientes.html', ingredientes=todos_ingredientes)


@app.route("/excluir_ingrediente_db/<int:ingrediente_id>", methods=["POST"])
def excluir_ingrediente_db(ingrediente_id):
    ingrediente = get_ingrediente_by_id(ingrediente_id)
    if not ingrediente:
        flash("Ingrediente não encontrado!", "error")
        return redirect(url_for('gerir_ingredientes'))
    if is_ingrediente_em_uso(ingrediente_id):
        flash(f"O ingrediente '{ingrediente['nome']}' não pode ser excluído porque está a ser utilizado.", "error")
        return redirect(url_for('gerir_ingredientes'))
    delete_ingrediente_db(ingrediente_id)
    flash(f"Ingrediente '{ingrediente['nome']}' excluído com sucesso!", "success")
    return redirect(url_for('gerir_ingredientes'))


# --- Rotas de Custos Adicionais ---
@app.route("/custos_adicionais")
def custos_adicionais():
    custos = get_custos_adicionais()
    return render_template("custos_adicionais.html", custos=custos)


@app.route("/novo_custo_adicional", methods=["GET", "POST"])
def novo_custo_adicional():
    if request.method == "POST":
        try:
            # 1. Obter dados do formulário
            nome = request.form['nome'].strip()
            tipo = request.form['tipo']
            custo_unitario = float(request.form['custo_unitario'])

            # Usar .get() para campos que podem estar vazios
            unidade_medida = request.form.get('unidade_medida')

            # Usar .get() com um valor padrão para números
            vida_util_str = request.form.get('vida_util')
            vida_util = int(vida_util_str) if vida_util_str and vida_util_str.isdigit() else None

            descricao = request.form.get('descricao')

            if not nome or not tipo or custo_unitario is None:
                flash("Nome, Tipo e Custo Unitário são obrigatórios.", "error")
                return render_template("novo_custo_adicional.html", **request.form)

            # 2. Chamar sua função do "Passo 4" para salvar no DB
            add_custo_adicional(nome, tipo, custo_unitario, unidade_medida, vida_util, descricao)

            flash(f"Custo '{nome}' adicionado com sucesso!", "success")
            return redirect(url_for('custos_adicionais'))  # Redirecionar de volta para a lista

        except Exception as e:
            flash(f"Erro ao adicionar custo: {e}", "error")
            # Re-renderiza o formulário mantendo os dados que o usuário digitou
            return render_template("novo_custo_adicional.html", **request.form)

    # Se for GET, apenas mostre a página
    return render_template("novo_custo_adicional.html")


@app.route("/editar_custo_adicional/<int:custo_id>", methods=["GET", "POST"])
def editar_custo_adicional(custo_id):
    # Busca o custo no DB
    custo = get_custo_adicional_by_id(custo_id)
    if not custo:
        flash("Custo adicional não encontrado!", "error")
        return redirect(url_for('custos_adicionais'))

    if request.method == "POST":
        try:
            # 1. Coletar dados do formulário
            nome = request.form['nome'].strip()
            tipo = request.form['tipo']
            custo_unitario = float(request.form['custo_unitario'])
            unidade_medida = request.form.get('unidade_medida')
            vida_util_str = request.form.get('vida_util')
            vida_util = int(vida_util_str) if vida_util_str and vida_util_str.isdigit() else None
            descricao = request.form.get('descricao')

            if not nome or not tipo or custo_unitario is None:
                flash("Nome, Tipo e Custo Unitário são obrigatórios.", "error")
                # Passa o 'custo' original de volta para o template em caso de erro
                return render_template("editar_custo_adicional.html", custo=custo)

            # 2. Chamar a função de atualização do DB
            update_custo_adicional(custo_id, nome, tipo, custo_unitario, unidade_medida, vida_util, descricao)

            flash(f"Custo '{nome}' atualizado com sucesso!", "success")
            return redirect(url_for('custos_adicionais'))

        except Exception as e:
            flash(f"Erro ao atualizar custo: {e}", "error")
            return render_template("editar_custo_adicional.html", custo=custo)

    # Se for GET, apenas mostra a página de edição com os dados do custo
    return render_template("editar_custo_adicional.html", custo=custo)


@app.route("/excluir_custo_adicional/<int:custo_id>", methods=["POST"])
def excluir_custo_adicional(custo_id):
    # (Opcional: Adicionar verificação se o custo está em uso em alguma receita)
    custo = get_custo_adicional_by_id(custo_id)
    if custo:
        delete_custo_adicional(custo_id)
        flash(f"Custo '{custo['nome']}' excluído com sucesso!", "success")
    else:
        flash("Custo não encontrado!", "error")
    return redirect(url_for('custos_adicionais'))


@app.route("/adicionar_custo_receita/<int:receita_id>", methods=["GET", "POST"])
def adicionar_custo_receita(receita_id):
    receita = get_receita(receita_id)
    if not receita:
        flash("Receita não encontrada!", "error")
        return redirect(url_for('gerir_receitas'))

    if request.method == "POST":
        try:
            custo_id = int(request.form['custo_adicional_id'])
            quantidade = float(request.form['quantidade_utilizada'])

            if not custo_id or quantidade <= 0:
                flash("Selecione um custo e uma quantidade válida.", "error")
            else:
                add_custo_adicional_receita(receita_id, custo_id, quantidade)
                flash("Custo adicionado à receita!", "success")

        except Exception as e:
            flash(f"Erro ao adicionar custo: {e}", "error")

        # Redireciona de volta para a mesma página (GET) para mostrar a lista atualizada
        return redirect(url_for('adicionar_custo_receita', receita_id=receita_id))

    # (Método GET)
    # Busca os custos que já estão na receita
    custos_na_receita = get_custos_adicionais_receita(receita_id)
    # Busca todos os custos disponíveis no catálogo
    todos_custos_disponiveis = get_custos_adicionais()

    return render_template("adicionar_custo_receita.html",
                           receita=receita,
                           custos_da_receita=custos_na_receita,
                           todos_custos=todos_custos_disponiveis)


@app.route("/excluir_custo_receita/<int:custo_receita_id>", methods=["POST"])
def excluir_custo_receita(custo_receita_id):
    # Usamos a nova função helper que criamos
    custo_associado = get_custo_adicional_receita_by_id(custo_receita_id)

    if custo_associado:
        # Guarda o ID da receita ANTES de deletar
        receita_id = custo_associado['receita_id']

        delete_custo_adicional_receita(custo_receita_id)
        flash("Custo removido da receita!", "success")

        # Redireciona de volta para a página de "adicionar custos" daquela receita
        return redirect(url_for('adicionar_custo_receita', receita_id=receita_id))

    flash("Associação de custo não encontrada!", "error")
    return redirect(url_for('gerir_receitas'))


# --- Rotas de Produtos
@app.route("/produtos")
def gerir_produtos():
    produtos = get_produtos()
    return render_template("gerir_produtos.html", produtos=produtos)


@app.route("/produtos/novo", methods=['GET', 'POST'])
def criar_produto():
    if request.method == 'POST':
        nome = request.form.get('nome')
        try:
            preco_venda = float(request.form.get('preco_venda'))
        except (ValueError, TypeError):
            flash("Preço de venda inválido.", "error")
            return redirect(url_for('criar_produto'))
        composicao_json = request.form.get('composicao_json')
        composicao = json.loads(composicao_json) if composicao_json else []
        if not nome or not preco_venda or not composicao:
            flash("Todos os campos são obrigatórios.", "error")
            return render_template('criar_produto.html', receitas=get_receitas())
        else:
            produto_id = add_produto(nome, preco_venda, composicao)
            if produto_id:
                flash(f"Produto '{nome}' criado com sucesso!", "success")
                return redirect(url_for('gerir_produtos'))
            else:
                flash(f"Já existe um produto com o nome '{nome}'.", "error")
                return render_template('criar_produto.html', receitas=get_receitas())
    receitas = get_receitas()
    return render_template('criar_produto.html', receitas=receitas)


@app.route("/produtos/excluir/<int:produto_id>", methods=['POST'])
def excluir_produto(produto_id):
    produto = get_produto_by_id(produto_id)
    if produto:
        delete_produto(produto_id)
        flash(f"Produto '{produto['nome']}' excluído com sucesso.", "success")
    else:
        flash("Produto não encontrado.", "error")
    return redirect(url_for('gerir_produtos'))


# --- Rotas Financeiras (Atualizadas) ---
@app.route("/financeiro/lancamentos", methods=['GET', 'POST'])
def lancamentos_financeiros():
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        if form_type == 'venda':
            try:
                data = request.form.get('data_venda')
                metodo_pagamento = request.form.get('metodo_pagamento')
                itens_json = request.form.get('venda_itens_json')
                venda_itens = json.loads(itens_json)
                if not venda_itens:
                    flash('Adicione pelo menos um item à venda.', 'error')
                else:
                    add_venda(venda_itens, data, metodo_pagamento)
                    flash('Venda registada com sucesso!', 'success')
            except Exception as e:
                flash(f'Erro ao registar venda: {e}', 'error')

        elif form_type == 'despesa':
            try:
                data = request.form.get('data_despesa')
                descricao = request.form.get('descricao')
                valor = float(request.form.get('valor'))
                categoria = request.form.get('categoria')
                add_despesa(descricao, valor, data, categoria)
                flash('Despesa registada com sucesso!', 'success')
            except Exception as e:
                flash(f'Erro ao registar despesa: {e}', 'error')

        return redirect(url_for('lancamentos_financeiros'))

    # --- LÓGICA GET ORIGINAL (apenas carrega produtos) ---
    produtos = get_produtos()
    return render_template('lancamentos.html', produtos=produtos)


@app.route("/financeiro/gerir")
def gerir_lancamentos():
    vendas_recentes = get_vendas_recentes(20)
    despesas_recentes = get_despesas_recentes(20)

    return render_template('gerir_lancamentos.html',
                           vendas=vendas_recentes,
                           despesas=despesas_recentes)

@app.route("/financeiro/excluir_venda/<int:venda_id>", methods=['POST'])
def excluir_venda(venda_id):
    try:
        delete_venda(venda_id)
        flash("Venda excluída com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao excluir venda: {e}", "error")
    # CORREÇÃO AQUI:
    return redirect(url_for('gerir_lancamentos'))

@app.route("/financeiro/excluir_despesa/<int:despesa_id>", methods=['POST'])
def excluir_despesa(despesa_id):
    try:
        delete_despesa(despesa_id)
        flash("Despesa excluída com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao excluir despesa: {e}", "error")
    # CORREÇÃO AQUI:
    return redirect(url_for('gerir_lancamentos'))


# --- Rotas Utilitárias ---
def executar_reset_db():
    try:
        close_connection(None)
        if os.path.exists(DATABASE):
            os.remove(DATABASE)
        init_db()
        flash("Banco de dados resetado com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao resetar o banco de dados: {e}", "error")

@app.route("/confirmar_reset", methods=["GET", "POST"])
def confirmar_reset():
    if request.method == "POST":
        senha_digitada = request.form.get("password")

        # 3. VERIFICA A SENHA DEFINIDA NO PASSO 1
        if senha_digitada == ADMIN_PASSWORD:
            # Senha correta: executa o reset e vai para o início
            executar_reset_db()
            return redirect(url_for("index"))
        else:
            # Senha incorreta: exibe erro e recarrega a página de senha
            flash("Senha incorreta. O banco de dados NÃO foi resetado.", "error")
            return redirect(url_for('confirmar_reset'))

    # Se for método GET, apenas mostra a página de confirmação
    return render_template("confirmar_reset.html")

@app.route("/debug/db")
def debug_db():
    if not app.debug:
        return "Acesso negado", 403
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row['name'] for row in cursor.fetchall()]
    db_data = {}
    for table_name in tables:
        cursor.execute(f"SELECT * FROM {table_name}")
        db_data[table_name] = cursor.fetchall()
    return render_template("debug.html", db_data=db_data, tables=tables)


# --- Execução do Aplicativo ---
if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5001)
