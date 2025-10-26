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
            id INTEGER PRIMARY KEY AUTOINCREMENT, descricao TEXT NOT NULL, valor REAL NOT NULL,
            data DATE NOT NULL, categoria TEXT )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS vendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data DATE NOT NULL, total_venda REAL NOT NULL, metodo_pagamento TEXT )''')

        # CORREÇÃO: Movido DROP TABLE para garantir que a estrutura seja sempre a mais recente ao recriar.
        cursor.execute("DROP TABLE IF EXISTS venda_itens")
        cursor.execute("DROP TABLE IF EXISTS produto_composicao")
        cursor.execute("DROP TABLE IF EXISTS produtos")

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
    cursor.execute("""
        SELECT pc.fracao_receita, r.id as receita_id
        FROM produto_composicao pc
        JOIN receitas r ON pc.receita_id = r.id
        WHERE pc.produto_id = ?
    """, (produto_id,))
    composicao = cursor.fetchall()
    custo_total_produto = 0
    for item in composicao:
        custo_total_da_receita = calcular_custo_total_receita(item['receita_id'])
        custo_total_produto += custo_total_da_receita * item['fracao_receita']
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


def get_dados_financeiros(periodo_dias=90):
    db = get_db()
    data_inicio = (datetime.now() - timedelta(days=periodo_dias)).strftime('%Y-%m-%d')
    vendas_df = pd.read_sql_query(f"SELECT * FROM vendas WHERE data >= ?", db, params=(data_inicio,))
    venda_itens_df = pd.read_sql_query("SELECT * FROM venda_itens", db)
    despesas_df = pd.read_sql_query(f"SELECT * FROM despesas WHERE data >= ?", db, params=(data_inicio,))
    produtos_df = pd.read_sql_query("SELECT id, nome FROM produtos", db)
    if not vendas_df.empty:
        vendas_df['data'] = pd.to_datetime(vendas_df['data'])
    if not despesas_df.empty:
        despesas_df['data'] = pd.to_datetime(despesas_df['data'])
    return vendas_df, venda_itens_df, despesas_df, produtos_df


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
        # ... (código existente)
        pass
    return render_template("novo_custo_adicional.html")


@app.route("/editar_custo_adicional/<int:custo_id>", methods=["GET", "POST"])
def editar_custo_adicional(custo_id):
    # ... (código existente)
    pass


@app.route("/excluir_custo_adicional/<int:custo_id>", methods=["POST"])
def excluir_custo_adicional(custo_id):
    # ... (código existente)
    pass


@app.route("/adicionar_custo_receita/<int:receita_id>", methods=["GET", "POST"])
def adicionar_custo_receita(receita_id):
    # ... (código existente)
    pass


@app.route("/excluir_custo_receita/<int:custo_receita_id>", methods=["POST"])
def excluir_custo_receita(custo_receita_id):
    # ... (código existente)
    pass


# --- Rotas de Produtos (NOVAS) ---
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
                return redirect(url_for('lancamentos_financeiros'))
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
                return redirect(url_for('lancamentos_financeiros'))
            except Exception as e:
                flash(f'Erro ao registar despesa: {e}', 'error')

    produtos = get_produtos()
    return render_template('lancamentos.html', produtos=produtos)


@app.route("/financeiro/dashboard")
def dashboard_financeiro():
    dados = get_dados_financeiros(periodo_dias=90)
    if dados is None:
        vendas_df = pd.DataFrame(columns=['data', 'total_venda', 'id'])
        venda_itens_df = pd.DataFrame(
            columns=['venda_id', 'produto_id', 'quantidade', 'preco_unitario_venda', 'custo_unitario_producao'])
        despesas_df = pd.DataFrame(columns=['valor'])
        produtos_df = pd.DataFrame(columns=['id', 'nome'])
    else:
        vendas_df, venda_itens_df, despesas_df, produtos_df = dados

    if not venda_itens_df.empty and not vendas_df.empty:
        venda_itens_df['lucro_item'] = (venda_itens_df['preco_unitario_venda'] - venda_itens_df[
            'custo_unitario_producao']) * venda_itens_df['quantidade']
        vendas_com_lucro_df = pd.merge(vendas_df, venda_itens_df, left_on='id', right_on='venda_id')
    else:
        vendas_com_lucro_df = pd.DataFrame(columns=['data', 'lucro_item', 'produto_id'])

    lucro_bruto_total = vendas_com_lucro_df['lucro_item'].sum()
    gasto_total_mensal = despesas_df['valor'].sum()
    lucro_liquido = lucro_bruto_total - gasto_total_mensal
    total_vendas = vendas_df['total_venda'].sum()

    # Criação dos Gráficos com Plotly
    fig_evolucao_lucro = go.Figure()
    if not vendas_com_lucro_df.empty and 'data' in vendas_com_lucro_df.columns and not vendas_com_lucro_df[
        'data'].isnull().all():
        lucro_semanal = vendas_com_lucro_df.set_index('data').resample('W-Mon', label='left', closed='left')[
            'lucro_item'].sum().reset_index()
        fig_evolucao_lucro.add_trace(
            go.Scatter(x=lucro_semanal['data'], y=lucro_semanal['lucro_item'], mode='lines+markers',
                       name='Lucro Bruto'))
    fig_evolucao_lucro.update_layout(title='Evolução do Lucro Bruto Semanal', xaxis_title='Semana',
                                     yaxis_title='Lucro (R$)')
    graph_evolucao_lucro_html = fig_evolucao_lucro.to_html(full_html=False, include_plotlyjs='cdn')

    if not venda_itens_df.empty and not produtos_df.empty:
        top_produtos_vendas = venda_itens_df.groupby('produto_id')['quantidade'].sum().nlargest(5).reset_index()
        top_produtos_vendas = pd.merge(top_produtos_vendas, produtos_df, left_on='produto_id', right_on='id')
        fig_top_vendas = px.bar(top_produtos_vendas, x='nome', y='quantidade',
                                title='Top 5 Produtos por Quantidade Vendida')
    else:
        fig_top_vendas = px.bar(title='Top 5 Produtos por Quantidade Vendida')
    graph_top_vendas_html = fig_top_vendas.to_html(full_html=False, include_plotlyjs='cdn')

    if not vendas_com_lucro_df.empty and not produtos_df.empty:
        top_produtos_lucro = vendas_com_lucro_df.groupby('produto_id')['lucro_item'].sum().nlargest(5).reset_index()
        top_produtos_lucro = pd.merge(top_produtos_lucro, produtos_df, left_on='produto_id', right_on='id')
        fig_top_lucro = px.bar(top_produtos_lucro, x='nome', y='lucro_item', title='Top 5 Produtos por Lucro Gerado')
    else:
        fig_top_lucro = px.bar(title='Top 5 Produtos por Lucro Gerado')
    graph_top_lucro_html = fig_top_lucro.to_html(full_html=False, include_plotlyjs='cdn')

    return render_template('dashboard.html',
                           lucro_bruto_total=lucro_bruto_total,
                           gasto_total_mensal=gasto_total_mensal,
                           lucro_liquido=lucro_liquido,
                           total_vendas=total_vendas,
                           graph_evolucao_lucro_html=graph_evolucao_lucro_html,
                           graph_top_vendas_html=graph_top_vendas_html,
                           graph_top_lucro_html=graph_top_lucro_html)


# --- Rotas Utilitárias ---
@app.route("/reset_db", methods=["POST"])
def reset_db():
    try:
        close_connection(None)
        if os.path.exists(DATABASE):
            os.remove(DATABASE)
        init_db()
        flash("Banco de dados resetado com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao resetar o banco de dados: {e}", "error")
    return redirect(url_for("index"))


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
