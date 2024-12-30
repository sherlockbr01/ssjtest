from io import BytesIO
import barcode
from barcode import Code128
from barcode.writer import ImageWriter
from flask import Flask, request, render_template, redirect, url_for, flash, session, jsonify, send_file
from functools import wraps
from datetime import datetime, timedelta
import sqlite3
import os
import locale
import logging
from reportlab.lib.pagesizes import A4, portrait
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Table, TableStyle, Spacer, SimpleDocTemplate, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, inch
from reportlab.lib import colors


app = Flask(__name__)
app.secret_key = '@ssjjti'  # Chave secreta para usar sessões

locale.setlocale(locale.LC_TIME, 'pt_BR.utf8')


def conectar_banco():
    conn = sqlite3.connect('ponto.db')
    return conn

def inicializa_banco():
    conn = conectar_banco()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    matricula TEXT UNIQUE NOT NULL,
                    senha TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pontos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL,
                    hora_entrada TEXT,
                    hora_saida TEXT,
                    hora_entrada_2 TEXT,
                    hora_saida_2 TEXT,
                    matricula_usuario TEXT NOT NULL,
                    FOREIGN KEY (matricula_usuario) REFERENCES usuarios (matricula))''')
    conn.commit()
    conn.close()

# Inicializar o banco de dados ao iniciar o aplicativo
inicializa_banco()

def verificar_permissao(permissoes):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'tipo' not in session or session['tipo'] not in permissoes:
                flash('Você não tem permissão para acessar esta página.', 'error')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/')
def home():
    return render_template('index.html')


# Rota de cadastro
@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    errors = {}
    token_administrador = "@ssjjti"

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip().title()
        matricula = request.form.get('matricula', '').strip().lower()
        senha = request.form.get('senha', '').strip()
        tipo = request.form.get('tipo', 'comum').strip()
        token = request.form.get('token', '').strip()

        if not nome:
            errors['nome'] = 'O campo Nome é obrigatório.'
        if not matricula:
            errors['matricula'] = 'O campo Matrícula é obrigatório.'
        if not senha:
            errors['senha'] = 'O campo Senha é obrigatório.'
        if tipo == 'admin' and token != token_administrador:
            errors['token'] = 'Token de Administrador inválido.'

        if not errors:
            conn = conectar_banco()
            if conn:
                c = conn.cursor()
                try:
                    c.execute("SELECT * FROM usuarios WHERE LOWER(matricula) = ?", (matricula,))
                    if c.fetchone():
                        flash('Matrícula já cadastrada!', 'error')
                    else:
                        c.execute("SELECT * FROM usuarios WHERE LOWER(nome) = ?", (nome.lower(),))
                        if c.fetchone():
                            flash('Nome já cadastrado!', 'error')
                        else:
                            c.execute(
                                "INSERT INTO usuarios (nome, matricula, senha, tipo, data_cadastro) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                                (nome, matricula, senha, tipo))
                            conn.commit()
                            return redirect(url_for('login', success=f'Usuário {nome} cadastrado com sucesso como {tipo}!'))  # Redireciona após sucesso
                except sqlite3.Error as e:
                    flash(f'Erro ao cadastrar o usuário: {e}', 'error')
                finally:
                    conn.close()
            else:
                flash('Erro ao conectar ao banco de dados.', 'error')

    return render_template('cadastro.html', errors=errors)
@app.route('/login', methods=['GET', 'POST'])
def login():
    success_message = request.args.get('success')
    errors = {}  # Inicializando um dicionário vazio para os erros

    if request.method == 'POST':
        matricula = request.form['matricula'].lower()
        senha = request.form['senha']

        # Aqui você pode adicionar a lógica de validação para erros específicos
        if not matricula or not senha:
            errors['matricula'] = 'Matrícula e senha são obrigatórios.'

        if not errors:
            conn = conectar_banco()
            c = conn.cursor()
            c.execute("SELECT * FROM usuarios WHERE matricula = ? AND senha = ?", (matricula, senha))
            usuario = c.fetchone()
            conn.close()
            if usuario:
                session['usuario'] = usuario[1]
                session['matricula'] = usuario[2]  # Armazenar a matrícula na sessão
                session['tipo'] = usuario[4]
                if usuario[4] == 'admin':
                    return redirect(url_for('dashboard_usuario_admin'))
                elif usuario[4] == 'seguranca':
                    return redirect(url_for('cadastrar_ponto'))
                else:
                    return redirect(url_for('dashboard_usuario_comum'))
            else:
                errors['matricula'] = 'Credenciais inválidas!'

    return render_template('login.html', success=success_message, errors=errors)


@app.route('/dashboard_usuario_admin')
@verificar_permissao(['admin'])
def dashboard_usuario_admin():
    conn = conectar_banco()
    c = conn.cursor()
    c.execute("SELECT tipo, COUNT(*) FROM usuarios GROUP BY tipo")
    user_counts = c.fetchall()
    conn.close()
    user_data = {
        'admin': 0,
        'comum': 0,
        'seguranca': 0
    }
    for user in user_counts:
        user_data[user[0]] = user[1]
    return render_template('dashboard_usuario_administrador.html', user_data=user_data)


@app.route('/usuarios', methods=['GET'])
@verificar_permissao(['admin'])
def usuarios():
    conn = conectar_banco()
    c = conn.cursor()

    search_query = request.args.get('search', '')
    search_matricula = request.args.get('matricula', '')
    filter_tipo = request.args.get('tipo', '')
    filter_date = request.args.get('data_cadastro', '')
    sort_by = request.args.get('sort_by', 'id')
    sort_order = request.args.get('sort_order', 'ASC')
    page = int(request.args.get('page', 1))
    per_page = 10
    offset = (page - 1) * per_page

    query = "SELECT id, nome, matricula, tipo, strftime('%d/%m/%Y', data_cadastro) as data_cadastro FROM usuarios WHERE 1=1"
    params = []

    if search_query:
        query += " AND nome LIKE ?"
        params.append(f'%{search_query}%')

    if search_matricula:
        query += " AND matricula LIKE ?"
        params.append(f'%{search_matricula}%')

    if filter_tipo:
        query += " AND tipo = ?"
        params.append(filter_tipo)

    if filter_date:
        query += " AND date(data_cadastro) = ?"
        params.append(filter_date)

    query += f" ORDER BY {sort_by} {sort_order} LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    c.execute(query, params)
    usuarios = c.fetchall()

    count_query = "SELECT COUNT(*) FROM usuarios WHERE 1=1"
    count_params = []

    if search_query:
        count_query += " AND nome LIKE ?"
        count_params.append(f'%{search_query}%')

    if search_matricula:
        count_query += " AND matricula LIKE ?"
        count_params.append(f'%{search_matricula}%')

    if filter_tipo:
        count_query += " AND tipo = ?"
        count_params.append(filter_tipo)

    if filter_date:
        count_query += " AND date(data_cadastro) = ?"
        count_params.append(filter_date)

    c.execute(count_query, count_params)
    total_usuarios = c.fetchone()[0]

    total_pages = (total_usuarios + per_page - 1) // per_page

    conn.close()
    return render_template('usuarios.html', usuarios=usuarios, total_pages=total_pages, current_page=page,
                           search_query=search_query, search_matricula=search_matricula, filter_tipo=filter_tipo,
                           filter_date=filter_date, sort_by=sort_by, sort_order=sort_order)



# Configurar o logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', handlers=[
    logging.FileHandler("app.log"),
    logging.StreamHandler()
])

@app.errorhandler(500)
def internal_server_error(error):
    logging.error(f'Erro interno do servidor: {error}')
    return render_template('500.html'), 500

@app.route('/editar_pontos/<int:usuario_id>', methods=['GET', 'POST'])
@verificar_permissao(['admin'])
def editar_pontos(usuario_id):
    conn = conectar_banco()
    c = conn.cursor()

    if request.method == 'POST':
        data = request.form.get('data')
        hora_entrada = request.form.get('hora_entrada')
        hora_saida = request.form.get('hora_saida')
        hora_entrada_2 = request.form.get('hora_entrada_2')
        hora_saida_2 = request.form.get('hora_saida_2')

        logging.info(f'Dados recebidos: data={data}, hora_entrada={hora_entrada}, hora_saida={hora_saida}, hora_entrada_2={hora_entrada_2}, hora_saida_2={hora_saida_2}, usuario_id={usuario_id}')

        try:
            c.execute("""
                UPDATE pontos
                SET hora_entrada = ?, hora_saida = ?, hora_entrada_2 = ?, hora_saida_2 = ?
                WHERE matricula_usuario = ? AND data = ?
            """, (hora_entrada, hora_saida, hora_entrada_2, hora_saida_2, usuario_id, data))
            conn.commit()
            logging.info(f'Ponto atualizado com sucesso para o usuário {usuario_id} na data {data}.')
            flash('Ponto Alterado com Sucesso!', 'success')
            return redirect(url_for('editar_pontos', usuario_id=usuario_id))
        except sqlite3.Error as e:
            logging.error(f'Erro ao atualizar o ponto: {e}')
            flash(f'Erro ao atualizar o ponto: {e}', 'error')
            return redirect(url_for('editar_pontos', usuario_id=usuario_id))
        finally:
            conn.close()
    else:
        c.execute("SELECT data FROM pontos WHERE matricula_usuario = ? ORDER BY data DESC", (usuario_id,))
        datas = c.fetchall()

        if not datas:
            flash('Nenhum ponto encontrado para o usuário fornecido.', 'error')
            return redirect(url_for('usuarios'))

        data_selecionada = datas[0][0]  # Selecionar a data mais recente por padrão
        c.execute("SELECT * FROM pontos WHERE matricula_usuario = ? AND data = ?", (usuario_id, data_selecionada))
        ponto = c.fetchone()

        ponto_formatado = {
            'data': ponto[1],
            'hora_entrada': ponto[2],
            'hora_saida': ponto[3],
            'hora_entrada_2': ponto[4],
            'hora_saida_2': ponto[5],
            'matricula': ponto[6]
        }

        return render_template('editar_pontos.html', datas=datas, ponto=ponto_formatado, usuario_id=usuario_id)

@app.route('/obter_ponto')
@verificar_permissao(['admin'])
def obter_ponto():
    data = request.args.get('data')
    usuario_id = request.args.get('usuario_id')

    conn = conectar_banco()
    c = conn.cursor()
    c.execute("SELECT * FROM pontos WHERE matricula_usuario = ? AND data = ?", (usuario_id, data))
    ponto = c.fetchone()
    conn.close()

    if ponto:
        ponto_formatado = {
            'data': ponto[1],
            'hora_entrada': ponto[2],
            'hora_saida': ponto[3],
            'hora_entrada_2': ponto[4],
            'hora_saida_2': ponto[5],
            'matricula': ponto[6]
        }
        return jsonify(ponto_formatado)
    else:
        return jsonify({'error': 'Ponto não encontrado'}), 404


@app.route('/gerar_usuarios_pdf', methods=['GET'])
@verificar_permissao(['admin'])
def gerar_usuarios_pdf():
    conn = conectar_banco()
    c = conn.cursor()

    search_query = request.args.get('search', '')
    search_matricula = request.args.get('matricula', '')
    filter_tipo = request.args.get('tipo', '')
    filter_date = request.args.get('data_cadastro', '')

    query = "SELECT nome, matricula FROM usuarios WHERE 1=1"
    params = []

    if search_query:
        query += " AND nome LIKE ?"
        params.append(f'%{search_query}%')

    if search_matricula:
        query += " AND matricula LIKE ?"
        params.append(f'%{search_matricula}%')

    if filter_tipo:
        query += " AND tipo = ?"
        params.append(filter_tipo)

    if filter_date:
        query += " AND date(data_cadastro) = ?"
        params.append(filter_date)

    c.execute(query, params)
    usuarios = c.fetchall()
    conn.close()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    styles = getSampleStyleSheet()
    title = Paragraph("Lista de Usuários", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 12))

    data = [["Nome", "Matrícula", "Código de Barras"]]
    for usuario in usuarios:
        nome, matricula = usuario
        barcode_class = barcode.get_barcode_class('code128')
        if barcode_class is None:
            continue
        code = barcode_class(matricula, writer=ImageWriter())
        barcode_buffer = BytesIO()
        code.write(barcode_buffer)
        barcode_buffer.seek(0)
        barcode_img = Image(barcode_buffer, width=200, height=50)
        data.append([nome, matricula, barcode_img])

    table = Table(data, colWidths=[7*cm, 4*cm, 6*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name='usuarios.pdf', mimetype='application/pdf')


@app.route('/editar_usuario/<int:id>', methods=['GET', 'POST'])
@verificar_permissao(['admin'])
def editar_usuario(id):
    conn = conectar_banco()
    c = conn.cursor()
    if request.method == 'POST':
        c.execute("SELECT nome, matricula, senha, tipo FROM usuarios WHERE id = ?", (id,))
        usuario_atual = c.fetchone()
        nome = request.form.get('nome', '').strip().title() or usuario_atual[0]
        matricula = request.form.get('matricula', '').strip().lower() or usuario_atual[1]
        senha = request.form.get('senha', '').strip() or usuario_atual[2]
        tipo = request.form.get('tipo', 'comum').strip() or usuario_atual[3]
        try:
            c.execute("UPDATE usuarios SET nome = ?, matricula = ?, senha = ?, tipo = ? WHERE id = ?",
                      (nome, matricula, senha, tipo, id))
            conn.commit()
            flash('Usuário atualizado com sucesso!', 'success')
            return redirect(url_for('usuarios'))
        except sqlite3.Error as e:
            flash(f'Erro ao atualizar o usuário: {e}', 'error')
        finally:
            conn.close()
    else:
        c.execute("SELECT * FROM usuarios WHERE id = ?", (id,))
        usuario = c.fetchone()
        conn.close()
        return render_template('editar_usuario.html', usuario=usuario)


@app.route('/excluir_usuario/<int:id>', methods=['POST'])
@verificar_permissao(['admin'])
def excluir_usuario(id):
    conn = conectar_banco()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM usuarios WHERE id = ?", (id,))
        conn.commit()
        flash('Usuário excluído com sucesso!', 'success')
    except sqlite3.Error as e:
        flash(f'Erro ao excluir o usuário: {e}', 'error')
    finally:
        conn.close()
    return redirect(url_for('usuarios'))


@app.route('/codigo_de_barras/<matricula>', methods=['GET'])
@verificar_permissao(['admin'])
def codigo_de_barras(matricula):
    conn = conectar_banco()
    c = conn.cursor()
    c.execute("SELECT * FROM usuarios WHERE matricula = ?", (matricula,))
    usuario = c.fetchone()
    conn.close()
    if usuario:
        barcode_class = barcode.get_barcode_class('code128')
        if barcode_class is None:
            return "Erro ao obter classe de código de barras", 500
        code = barcode_class(matricula, writer=ImageWriter())
        buffer = BytesIO()
        code.write(buffer)
        buffer.seek(0)
        return send_file(buffer, mimetype='image/png')
    return "Usuário não encontrado", 404


@app.route('/static/images/<filename>')
def send_barcode(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard_usuario_comum')
@verificar_permissao(['comum'])
def dashboard_usuario_comum():
    usuario_nome = session['usuario']
    matricula = session['matricula']  # Certifique-se de que a matrícula está armazenada na sessão

    # Buscar pontos recentes do usuário
    conn = conectar_banco()
    c = conn.cursor()
    c.execute(
        "SELECT data, hora_entrada, hora_saida, hora_entrada_2, hora_saida_2 FROM pontos WHERE matricula_usuario = ? ORDER BY data DESC LIMIT 10",
        (matricula,))
    pontos = c.fetchall()
    conn.close()

    # Formatar pontos para exibição
    pontos_formatados = []
    for ponto in pontos:
        data_formatada = datetime.strptime(ponto[0], "%Y-%m-%d").strftime("%d/%m/%Y")

        # Calcular horas trabalhadas
        horas_trabalhadas = calcular_horas_trabalhadas(
            ponto[1], ponto[2], ponto[3], ponto[4]
        )

        pontos_formatados.append({
            'data': data_formatada,
            'hora_entrada': ponto[1],
            'hora_saida': ponto[2],
            'hora_entrada_2': ponto[3],
            'hora_saida_2': ponto[4],
            'horas_trabalhadas': horas_trabalhadas
        })

    return render_template('dashboard_usuario_comum.html', usuario_nome=usuario_nome, matricula=matricula,
                           pontos=pontos_formatados)


def calcular_horas_trabalhadas(hora_entrada, hora_saida, hora_entrada_2, hora_saida_2):
    formato = "%H:%M:%S"
    total_horas = timedelta()

    if hora_entrada and hora_saida:
        entrada = datetime.strptime(hora_entrada, formato)
        saida = datetime.strptime(hora_saida, formato)
        total_horas += saida - entrada

    if hora_entrada_2 and hora_saida_2:
        entrada_2 = datetime.strptime(hora_entrada_2, formato)
        saida_2 = datetime.strptime(hora_saida_2, formato)
        total_horas += saida_2 - entrada_2

    return str(total_horas)


@app.route('/cadastrar_ponto', methods=['GET', 'POST'])
@verificar_permissao(['admin', 'seguranca'])
def cadastrar_ponto():
    if 'usuario' not in session or session.get('tipo') not in ['admin', 'seguranca']:
        return redirect(url_for('login'))

    if request.method == 'POST':
        data_atual = datetime.now().strftime("%Y-%m-%d")
        hora_atual = datetime.now().strftime("%H:%M:%S")
        matricula = request.json.get('matricula')

        if not matricula:
            return jsonify({'mensagem': 'Matrícula não fornecida.'}), 400

        conn = conectar_banco()
        c = conn.cursor()
        c.execute("SELECT * FROM pontos WHERE data = ? AND matricula_usuario = ?", (data_atual, matricula))
        pontos = c.fetchall()

        if len(pontos) >= 4:
            conn.close()
            return jsonify({'mensagem': 'Limite de 4 pontos diários atingido.'}), 400

        if not pontos:
            # Inserir um novo ponto para o usuário
            c.execute("INSERT INTO pontos (data, hora_entrada, matricula_usuario) VALUES (?, ?, ?)",
                      (data_atual, hora_atual, matricula))
        else:
            ponto = pontos[0]
            if not ponto[2]:  # Se a coluna hora_entrada está vazia
                c.execute("UPDATE pontos SET hora_entrada = ? WHERE id = ?", (hora_atual, ponto[0]))
            elif not ponto[3]:  # Se a coluna hora_saida está vazia
                c.execute("UPDATE pontos SET hora_saida = ? WHERE id = ?", (hora_atual, ponto[0]))
            elif not ponto[4]:  # Se a coluna hora_entrada_2 está vazia
                c.execute("UPDATE pontos SET hora_entrada_2 = ? WHERE id = ?", (hora_atual, ponto[0]))
            elif not ponto[5]:  # Se a coluna hora_saida_2 está vazia
                c.execute("UPDATE pontos SET hora_saida_2 = ? WHERE id = ?", (hora_atual, ponto[0]))
            else:
                conn.close()
                return jsonify({'mensagem': 'Limite de 4 pontos diários já atingido.'}), 400

        conn.commit()
        conn.close()
        return jsonify({'mensagem': 'Ponto registrado com sucesso!'})

    # Paginação de pontos
    page = request.args.get('page', 1, type=int)
    limit = 10
    offset = (page - 1) * limit

    conn = conectar_banco()
    c = conn.cursor()

    data_atual = datetime.now().strftime("%Y-%m-%d")

    # Calcular o total de pontos para paginar corretamente
    c.execute("SELECT COUNT(*) FROM pontos WHERE data = ?", (data_atual,))
    total_pontos = c.fetchone()[0]

    # Modificar a consulta para garantir que o ponto mais recente do usuário vá para o topo da lista
    c.execute("""
        SELECT p.data, p.hora_entrada, p.hora_saida, p.hora_entrada_2, p.hora_saida_2, u.nome
        FROM pontos p
        JOIN usuarios u ON p.matricula_usuario = u.matricula
        WHERE p.data = ?
        ORDER BY
            CASE WHEN p.matricula_usuario = (SELECT matricula_usuario FROM pontos WHERE data = ? ORDER BY data DESC LIMIT 1) THEN 1 ELSE 2 END,
            p.data DESC
        LIMIT ? OFFSET ?
    """, (data_atual, data_atual, limit, offset))

    pontos = c.fetchall()
    conn.close()

    pontos_formatados = []
    for ponto in pontos:
        data, hora_entrada, hora_saida, hora_entrada_2, hora_saida_2, nome = ponto
        data_formatada = datetime.strptime(data, "%Y-%m-%d").strftime("%d/%m/%y")
        nome_abreviado = ' '.join(nome.split()[:2])
        pontos_formatados.append(
            [data_formatada, hora_entrada, hora_saida, hora_entrada_2, hora_saida_2, nome_abreviado])

    total_pages = (total_pontos + limit - 1) // limit
    return render_template('cadastrar_ponto.html', pontos=pontos_formatados, total_pages=total_pages, current_page=page)

@app.route('/pontos', methods=['GET'])
def buscar_pontos():
    pagina = int(request.args.get('pagina', 1))
    limite = 10
    offset = (pagina - 1) * limite
    conn = conectar_banco()
    c = conn.cursor()
    data_atual = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT p.data, p.hora_entrada, p.hora_saida, p.hora_entrada_2, p.hora_saida_2, u.nome "
              "FROM pontos p JOIN usuarios u ON p.matricula_usuario = u.matricula "
              "WHERE p.data = ? ORDER BY p.data DESC LIMIT ? OFFSET ?", (data_atual, limite, offset))
    pontos = c.fetchall()
    conn.close()

    pontos_formatados = []
    for ponto in pontos:
        data, hora_entrada, hora_saida, hora_entrada_2, hora_saida_2, nome = ponto
        data_formatada = datetime.strptime(data, "%Y-%m-%d").strftime("%d/%m/%Y")
        nome_abreviado = ' '.join(nome.split()[:2])
        pontos_formatados.append(
            [data_formatada, hora_entrada, hora_saida, hora_entrada_2, hora_saida_2, nome_abreviado])

    return jsonify(pontos_formatados)

@app.route('/contar_pontos_totais', methods=['GET'])
def contar_pontos_totais():
    conn = conectar_banco()
    c = conn.cursor()
    data_atual = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM pontos WHERE data = ?", (data_atual,))
    total_pontos = c.fetchone()[0]
    conn.close()
    return jsonify({"totalPontos": total_pontos})


@app.route('/listar_usuarios', methods=['GET'])
def buscar_usuarios():
    search_term = request.args.get('q', '')  # Obtém o termo de busca
    conn = conectar_banco()
    c = conn.cursor()

    # Ajustar a consulta para filtrar por nome ou matrícula
    c.execute("SELECT nome, matricula FROM usuarios WHERE nome LIKE ? OR matricula LIKE ?",
              ('%' + search_term + '%', '%' + search_term + '%'))

    usuarios = c.fetchall()
    conn.close()

    return jsonify(usuarios)


# Função para calcular o saldo final de horas
def calcular_saldo_final(total_horas_extra, total_horas_devedoras):
    total_extra_segundos = total_horas_extra.total_seconds()
    total_devedor_segundos = total_horas_devedoras.total_seconds()
    saldo_final_segundos = total_extra_segundos - total_devedor_segundos
    saldo_final = timedelta(seconds=abs(saldo_final_segundos))
    if saldo_final_segundos >= 0:
        return saldo_final, "extra"
    else:
        return saldo_final, "devedor"

# Função para calcular as horas trabalhadas em formato avançado
def calcular_horas_trabalhadas_relatorio_avancado(entradas_saidas):
    horas_totais = timedelta()
    if entradas_saidas[0] and entradas_saidas[1]:
        entrada1 = datetime.strptime(entradas_saidas[0], "%H:%M:%S")
        saida1 = datetime.strptime(entradas_saidas[1], "%H:%M:%S")
        horas_totais += saida1 - entrada1
    if entradas_saidas[2] and entradas_saidas[3]:
        entrada2 = datetime.strptime(entradas_saidas[2], "%H:%M:%S")
        saida2 = datetime.strptime(entradas_saidas[3], "%H:%M:%S")
        horas_totais += saida2 - entrada2
    return horas_totais


# Função para calcular horas extras ou devedoras
def calcular_extra_devedor(horas_trabalhadas, carga_horaria_padrao):
    carga_horaria_padrao = timedelta(hours=carga_horaria_padrao)
    horas_trabalhadas_timedelta = timedelta(hours=int(horas_trabalhadas.split(":")[0]),
                                            minutes=int(horas_trabalhadas.split(":")[1]),
                                            seconds=int(horas_trabalhadas.split(":")[2]))
    diferenca = horas_trabalhadas_timedelta - carga_horaria_padrao
    if diferenca.total_seconds() < 0:
        diferenca = abs(diferenca)
        return f"-{str(diferenca)}", 'devedor'
    else:
        return str(diferenca), 'extra'


# Função para formatar a data
def formatar_data(data_str):
    data = datetime.strptime(data_str, "%Y-%m-%d")
    dia = data.strftime("%d")
    mes_ano = data.strftime("%b %y").lower()
    data_formatada = f"{dia} {mes_ano}"

    dia_semana = data.strftime("%A").capitalize()
    return f"{data_formatada}<br/>{dia_semana}"


# Função para formatar o intervalo de datas
def formatar_intervalo_data(data_inicio, data_fim):
    data_inicio_obj = datetime.strptime(data_inicio, "%Y-%m-%d")
    data_fim_obj = datetime.strptime(data_fim, "%Y-%m-%d")
    data_inicio_formatada = data_inicio_obj.strftime("%d")
    data_fim_formatada = data_fim_obj.strftime("%d")
    mes_inicio = data_inicio_obj.strftime("%b").lower()
    mes_fim = data_fim_obj.strftime("%b").lower()
    ano = data_inicio_obj.year

    if mes_inicio == mes_fim:
        return f"De {data_inicio_formatada} a {data_fim_formatada} de {mes_inicio} de {ano}"
    else:
        return f"De {data_inicio_formatada} de {mes_inicio} a {data_fim_formatada} de {mes_fim} de {ano}"


# Função para formatar nome
def formatar_nome(nome_completo):
    nomes = nome_completo.split()
    return " ".join([nome.capitalize() for nome in nomes])

# Função para formatar timedelta avançado
def format_timedelta_avancado(td):
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


# Função principal de geração do PDF
def gerar_pdf_avancado(data_inicio, data_fim, usuario, tipo_relatorio, pontos, carga_horaria_padrao):
    try:
        buffer = BytesIO()

        # Estilos do documento
        styles = getSampleStyleSheet()

        # Estilo para o título
        title_style = ParagraphStyle('Title', parent=styles['Normal'], fontName='Times-Bold', fontSize=12,
                                     alignment=1, spaceAfter=12)

        # Estilo para cabeçalho em negrito
        header_style_bold = ParagraphStyle('HeaderBold', parent=styles['Normal'], fontName='Times-Bold',
                                           fontSize=11, spaceAfter=0)

        # Estilo normal
        normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontName='Times-Roman', fontSize=9,
                                      alignment=0, spaceAfter=0)

        # Iniciando o documento PDF
        doc = BaseDocTemplate(buffer, pagesize=portrait(A4),
                              rightMargin=0.75 * inch, leftMargin=0.75 * inch,
                              topMargin=0.2 * inch, bottomMargin=0.75 * inch)

        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height - 2 * cm, id='normal')
        doc.addPageTemplates([PageTemplate(id='main', frames=frame)])

        elements = []

        # Adicionando o título no topo
        elements.append(Paragraph("JUSTIÇA FEDERAL SUBSEÇÃO JUDICIÁRIA DE JATAÍ", title_style))

        # Cabeçalho abaixo do título
        elements.append(Spacer(1, 6))

        header_data = [
            [Paragraph("Nome:", header_style_bold), Paragraph(formatar_nome(usuario), normal_style)],
            [Paragraph("Data Filtrada:", header_style_bold),
             Paragraph(formatar_intervalo_data(data_inicio, data_fim), normal_style)],
            [Paragraph("Relatório:", header_style_bold), Paragraph('Avançado', normal_style)],
            [Paragraph("C. Horária:", header_style_bold),
             Paragraph(f"{carga_horaria_padrao} horas diárias", normal_style)]
        ]

        # Criando a tabela com os dados do cabeçalho
        header_table = Table(header_data, colWidths=[3 * cm, None])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Times-Roman'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4)
        ]))

        # Adicionando a tabela ao documento
        elements.append(header_table)

        # Tabela de pontos
        elements.append(Spacer(1, 6))
        dados = [["Data", "Entrada", "Saída", "Entrada 2", "Saída 2", "Total Horas", "Extra/Devedor"]]
        total_horas_trabalhadas = timedelta()
        total_horas_extra = timedelta()
        total_horas_devedoras = timedelta()

        pontos.sort(key=lambda x: x['data'])

        for ponto in pontos:
            horas_trabalhadas = calcular_horas_trabalhadas_relatorio_avancado(
                [ponto['hora_entrada'], ponto['hora_saida'], ponto['hora_entrada_2'], ponto['hora_saida_2']])
            diferenca, tipo = calcular_extra_devedor(format_timedelta_avancado(horas_trabalhadas), carga_horaria_padrao)
            data_formatada = formatar_data(ponto['data'])
            if tipo == 'devedor':
                extra_devedor_para = Paragraph(f'<font color="red">{diferenca}</font>', normal_style)
            else:
                extra_devedor_para = Paragraph(diferenca, normal_style)

            dados.append([
                Paragraph(data_formatada, normal_style),
                ponto['hora_entrada'],
                ponto['hora_saida'],
                ponto['hora_entrada_2'],
                ponto['hora_saida_2'],
                format_timedelta_avancado(horas_trabalhadas),
                extra_devedor_para
            ])

            if tipo == 'extra':
                horas, minutos, segundos = map(int, diferenca.split(':'))
                total_horas_extra += timedelta(hours=horas, minutes=minutos, seconds=segundos)
            else:
                horas, minutos, segundos = map(int, diferenca[1:].split(':'))
                total_horas_devedoras += timedelta(hours=horas, minutes=minutos, seconds=segundos)

            total_horas_trabalhadas += horas_trabalhadas

        # Criando a tabela de pontos
        pontos_table = Table(dados, hAlign='CENTER')
        pontos_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), 'Times-Roman'),
            ('FONTNAME', (0, 0), (-1, 0), 'Times-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4)
        ]))
        elements.append(pontos_table)

        # Saldo final
        saldo_final, tipo = calcular_saldo_final(total_horas_extra, total_horas_devedoras)
        if tipo == 'devedor':
            saldo_final_para = Paragraph(
                f'<para alignment="center" spaceb="3" spacea="3" borderColor="black" borderWidth="1"><font color="red">Saldo final: {format_timedelta_avancado(saldo_final)} ({tipo})</font></para>',
                normal_style
            )
        else:
            saldo_final_para = Paragraph(
                f'<para alignment="center" spaceb="3" spacea="3" borderColor="black" borderWidth="1">Saldo final: {format_timedelta_avancado(saldo_final)} ({tipo})</para>',
                normal_style
            )

        elements.append(Spacer(1, 6))
        elements.append(saldo_final_para)

        # Após o saldo final, aumente o espaçamento
        elements.append(Spacer(1, 18))  # Aumentando o espaçamento entre o saldo final e a assinatura

        # Adicionar assinatura
        elements.append(Spacer(1, 12))  # Espaço adicional para a linha de assinatura
        elements.append(Paragraph("______________________________", normal_style))  # Linha de assinatura
        elements.append(Spacer(1, 6))  # Espaço entre a linha de assinatura e o nome

        # Nome do usuário e data na mesma linha
        nome_e_data_style = ParagraphStyle('NomeData', parent=normal_style, alignment=0)  # Alinhamento à esquerda
        data_style = ParagraphStyle('DataRight', parent=normal_style, alignment=2)  # Alinhamento à direita

        # Adiciona o nome do usuário
        elements.append(Paragraph(formatar_nome(usuario), nome_e_data_style))

        # Adicionar data na posição desejada (mesma linha, alinhado à direita)
        data_atual = datetime.today().strftime('%d %b de %Y').title()
        elements.append(Spacer(1, -11))  # Ajuste para garantir que a data e o nome fiquem na mesma linha
        elements.append(Paragraph(f"Jataí, {data_atual}", data_style))  # Data de assinatura

        # Construir o PDF
        doc.build(elements)

        # Verificar o conteúdo do buffer
        if not buffer.getvalue():
            print("PDF gerado em branco.")
        else:
            print("PDF gerado com sucesso.")

        return buffer

    except Exception as e:
        print(f"Erro ao gerar PDF: {e}")
        return None


@app.route('/relatorios', methods=['GET', 'POST'])
def relatorios():
    mensagem_confirmacao = None
    data_inicio = None
    data_fim = None

    if request.method == 'POST':
        tipo_relatorio = request.form.get('tipo_relatorio')
        tipo_periodo = request.form.get('tipo_periodo')
        usuario_nome = request.form.get('usuario')
        carga_horaria_selecionada = request.form.get('carga_horaria')

        # Definir carga horária padrão
        carga_horaria_padrao = 7  # Carga horária padrão de 7 horas
        if carga_horaria_selecionada == "08 Horas":
            carga_horaria_padrao = 8  # Altera a carga horária para 8 horas

        # Definir as datas de início e fim com base no tipo de período selecionado
        if tipo_periodo == "hoje":
            hoje = datetime.today()
            data_inicio = hoje.strftime('%Y-%m-%d')
            data_fim = hoje.strftime('%Y-%m-%d')
        elif tipo_periodo == "semanal":
            hoje = datetime.today()
            inicio_semana = hoje - timedelta(days=hoje.weekday())  # Segunda-feira da semana atual
            fim_semana = inicio_semana + timedelta(days=6)         # Domingo da semana atual
            data_inicio = inicio_semana.strftime('%Y-%m-%d')
            data_fim = fim_semana.strftime('%Y-%m-%d')
        elif tipo_periodo == "mensal":
            hoje = datetime.today()
            inicio_mes = hoje.replace(day=1)                        # Primeiro dia do mês
            proximo_mes = hoje.replace(day=28) + timedelta(days=4)  # Garante o próximo mês
            fim_mes = proximo_mes - timedelta(days=proximo_mes.day) # Último dia do mês
            data_inicio = inicio_mes.strftime('%Y-%m-%d')
            data_fim = fim_mes.strftime('%Y-%m-%d')
        elif tipo_periodo == "entre-datas":
            data_inicio = request.form.get('data_inicio')
            data_fim = request.form.get('data_fim')
            mensagem_confirmacao = f"Período selecionado: <span class='data-inicio'>{data_inicio}</span> a <span class='data-fim'>{data_fim}</span>"

        # Mensagem de confirmação de datas
        flash('Datas de filtro aplicadas com sucesso!', 'success')

        # Conectar ao banco de dados
        conn = conectar_banco()
        c = conn.cursor()
        query = '''
                SELECT p.data, p.hora_entrada, p.hora_saida, p.hora_entrada_2, p.hora_saida_2, u.nome
                FROM pontos p
                JOIN usuarios u ON p.matricula_usuario = u.matricula
                WHERE p.data BETWEEN ? AND ? AND u.nome LIKE ?
                ORDER BY p.data DESC, p.hora_entrada ASC
            '''
        c.execute(query, (data_inicio, data_fim, f'%{usuario_nome}%'))

        pontos = [{
            'data': linha[0], 'hora_entrada': linha[1], 'hora_saida': linha[2],
            'hora_entrada_2': linha[3], 'hora_saida_2': linha[4], 'nome': linha[5]
        } for linha in c.fetchall()]

        conn.close()

        if not pontos:
            flash('Nenhum ponto encontrado para o período selecionado.', 'warning')
            return redirect(url_for('relatorios'))

        # Gerar o PDF de acordo com o tipo de relatório selecionado
        buffer = gerar_pdf_avancado(data_inicio, data_fim, usuario_nome, tipo_relatorio, pontos, carga_horaria_padrao)

        if buffer:
            buffer.seek(0)
            return send_file(buffer, as_attachment=True, download_name="relatorio_pontos.pdf", mimetype='application/pdf')
        else:
            flash('Erro ao gerar o PDF. Por favor, tente novamente.', 'error')
            return redirect(url_for('relatorios'))

    else:
        # Se for um GET, carregar o formulário de relatórios
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        if data_inicio and data_fim:
            mensagem_confirmacao = f"Período selecionado: <span class='data-inicio'>{data_inicio}</span> a <span class='data-fim'>{data_fim}</span>"

        conn = conectar_banco()
        c = conn.cursor()
        c.execute("SELECT nome, matricula FROM usuarios ORDER BY nome")
        usuarios = c.fetchall()
        conn.close()

        return render_template('relatorios.html', usuarios=usuarios, mensagem_confirmacao=mensagem_confirmacao)

def validar_hora(hora):
    try:
        datetime.strptime(hora, '%H:%M:%S')
        return True
    except ValueError:
        return False



@app.route('/select-dates', methods=['GET', 'POST'])
@verificar_permissao(['admin'])
def select_dates():
    if request.method == 'POST':
        # Recebe as datas do formulário do modal
        data_inicio = request.form.get('data_inicio_popup')
        data_fim = request.form.get('data_fim_popup')

        # Redireciona de volta para a página de relatórios com as datas preenchidas
        return redirect(url_for('relatorios', data_inicio=data_inicio, data_fim=data_fim))

    return render_template('popup_data.html')


if __name__ == '__main__':
    app.run(debug=True)
