from flask import Flask, render_template, request, redirect, url_for, flash, session
import mysql.connector
import string
import random
from decimal import Decimal
from datetime import date, datetime, timedelta
import secrets

app = Flask(__name__)
app.secret_key = 'super_secret_key_2026_change_to_stronger'  # 建议改成更复杂的
# 【新增这三行：彻底禁用缓存，强制每次加载最新样式】
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['DEBUG'] = True

def get_db_connection():
    try:
        return mysql.connector.connect(
            host='localhost',
            user='db_admin',
            password='admin123',  # ←←← 请确保这里是正确的密码
            database='library_db',
            charset='utf8mb4'
        )
    except mysql.connector.Error as err:
        print(f"数据库连接失败：{err}")
        return None


# ==================== 登录验证装饰器 ====================
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def generate_referral_code(length=8):
    """生成唯一的大写邀请码"""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choice(chars) for _ in range(length))
        conn = get_db_connection()
        if not conn:
            return code  # 连接失败也返回，避免卡死
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM Readers WHERE referral_code = %s", (code,))
        if not cursor.fetchone():
            conn.close()
            return code
        conn.close()


# 论坛主页：显示所有帖子
@app.route('/forum')
def forum():
    conn = get_db_connection()
    if not conn:
        return render_template('forum.html', posts=[])

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT 
            p.post_id, 
            p.content, 
            p.created_at,
            r.name, 
            r.username,
            r.reader_id AS post_reader_id,
            COUNT(c.comment_id) AS comment_count
        FROM Posts p
        JOIN Readers r ON p.reader_id = r.reader_id
        LEFT JOIN Comments c ON p.post_id = c.post_id
        GROUP BY p.post_id
        ORDER BY p.created_at DESC
        LIMIT 100
    """)

    posts = cursor.fetchall()
    conn.close()

    return render_template('forum.html', posts=posts)


@app.route('/add_post', methods=['GET', 'POST'])
@login_required
def add_post():
    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        if not content:
            flash('帖子内容不能为空', 'danger')
            return redirect(url_for('add_post'))

        if len(content) > 1000:
            flash('帖子内容不能超过1000字', 'danger')
            return redirect(url_for('add_post'))

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO Posts (reader_id, content, created_at)
            VALUES (%s, %s, NOW())
        """, (session['user_id'], content))
        conn.commit()
        conn.close()

        flash('发布成功！', 'success')
        return redirect(url_for('forum'))

    # GET：显示发帖页面
    return render_template('add_post.html')


# 发布新帖子
@app.route('/post_new', methods=['POST'])
@login_required
def post_new():
    content = request.form.get('content', '').strip()
    if not content:
        flash('帖子内容不能为空', 'danger')
        return redirect(url_for('forum'))

    # 暂时不处理图片上传，先留空（后续可扩展）
    image_url = None

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO Posts (reader_id, content, image_url)
        VALUES (%s, %s, %s)
    """, (session['user_id'], content, image_url))
    conn.commit()
    conn.close()

    flash('发布成功！', 'success')
    return redirect(url_for('forum'))


# 帖子详情页（查看评论 + 发表评论）
@app.route('/post/<int:post_id>')
def post_detail(post_id):
    if 'user_id' not in session:
        flash('请先登录才能查看帖子详情', 'warning')
        return redirect(url_for('login'))

    conn = get_db_connection()
    if not conn:
        flash('数据库连接失败', 'danger')
        return redirect(url_for('forum'))

    cursor = conn.cursor(dictionary=True)

    # 获取帖子详情
    cursor.execute("""
        SELECT p.*, r.name, r.username, r.reader_id AS post_reader_id
        FROM Posts p
        JOIN Readers r ON p.reader_id = r.reader_id
        WHERE p.post_id = %s
    """, (post_id,))
    post = cursor.fetchone()
    if not post:
        flash('帖子不存在或已被删除', 'danger')
        conn.close()
        return redirect(url_for('forum'))

    # 获取所有评论 —— 关键！必须选出 r.reader_id
    cursor.execute("""
        SELECT 
            c.comment_id, 
            c.content, 
            c.created_at, 
            r.name, 
            r.username, 
            r.reader_id
        FROM Comments c
        JOIN Readers r ON c.reader_id = r.reader_id
        WHERE c.post_id = %s
        ORDER BY c.created_at ASC
    """, (post_id,))
    comments = cursor.fetchall()

    # 【强制调试输出】看控制台是否有 reader_id
    print("\n=== 论坛帖子详情调试信息 ===")
    print(f"当前登录用户: ID={session.get('user_id')}, 用户名={session.get('username')}")
    print(f"帖子ID: {post_id}")
    print("评论列表:")
    for c in comments:
        print(f"  - 评论ID: {c['comment_id']}, "
              f"作者: {c['name']} (@{c['username']}), "
              f"reader_id: {c['reader_id']}, "
              f"内容: {c['content'][:30]}...")
    print("============================\n")

    conn.close()
    return render_template('post_detail.html', post=post, comments=comments)




# 发表评论
@app.route('/comment/<int:post_id>', methods=['POST'])
@login_required
def add_comment(post_id):
    content = request.form.get('content', '').strip()
    if not content:
        flash('评论不能为空', 'danger')
        return redirect(url_for('post_detail', post_id=post_id))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO Comments (post_id, reader_id, content)
        VALUES (%s, %s, %s)
    """, (post_id, session['user_id'], content))
    conn.commit()
    conn.close()

    flash('评论成功', 'success')
    return redirect(url_for('post_detail', post_id=post_id))


# 删除自己的帖子
@app.route('/delete_post/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 只能删自己的，或管理员可删任何
    if session.get('role') == 'admin':
        cursor.execute("DELETE FROM Posts WHERE post_id = %s", (post_id,))
    else:
        cursor.execute("DELETE FROM Posts WHERE post_id = %s AND reader_id = %s",
                       (post_id, session['user_id']))

    affected = cursor.rowcount
    conn.commit()
    conn.close()

    if affected:
        flash('帖子已删除', 'info')
    else:
        flash('无权限或帖子不存在', 'danger')

    return redirect(url_for('forum'))


# 删除评论（自己或管理员可删）
@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
@login_required
def delete_comment(comment_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 先查出这条评论属于哪个帖子（用于跳转回去）
    cursor.execute("SELECT post_id, reader_id FROM Comments WHERE comment_id = %s", (comment_id,))
    comment = cursor.fetchone()

    if not comment:
        flash('评论不存在', 'danger')
        conn.close()
        return redirect(url_for('forum'))

    post_id, comment_reader_id = comment

    # 权限判断：自己发的或管理员
    if session.get('role') == 'admin' or comment_reader_id == session['user_id']:
        cursor.execute("DELETE FROM Comments WHERE comment_id = %s", (comment_id,))
        conn.commit()
        flash('评论已删除', 'info')
    else:
        flash('无权限删除此评论', 'danger')

    conn.close()
    return redirect(url_for('post_detail', post_id=post_id))


# ==================== 座位预约系统（完整修复版）===================

@app.route('/seats')
@login_required
def seats():
    conn = get_db_connection()
    if not conn:
        flash('数据库连接失败', 'danger')
        return render_template('seats.html', rooms=[], current_booking=None)

    cursor = conn.cursor(dictionary=True)

    # 获取所有座位及当前有效预订（未过期 + active）
    cursor.execute("""
        SELECT 
            r.room_id, r.name AS room_name,
            s.seat_id, s.seat_number,
            sb.booking_id,
            sb.reader_id AS booked_reader_id,
            sb.start_time,
            sb.end_time,
            u.name AS booked_reader_name
        FROM Rooms r
        JOIN Seats s ON r.room_id = s.room_id
        LEFT JOIN SeatBookings sb ON s.seat_id = sb.seat_id 
            AND sb.status = 'active'
            AND sb.end_time > NOW()
        LEFT JOIN Readers u ON sb.reader_id = u.reader_id
        ORDER BY r.room_id, s.seat_number
    """)
    all_seats = cursor.fetchall()

    # 按房间分组
    rooms = {}
    for row in all_seats:
        room_name = row['room_name']
        if room_name not in rooms:
            rooms[room_name] = {'room_id': row['room_id'], 'name': room_name, 'seats': []}
        seat = {
            'seat_id': row['seat_id'],
            'seat_number': row['seat_number'],
            'is_booked': row['booking_id'] is not None,
            'booked_reader_name': row['booked_reader_name'],
            'start_time': row['start_time'],
            'end_time': row['end_time'],
            'can_book': row['booking_id'] is None,
            'is_mine': row['booked_reader_id'] == session['user_id'] if row['booked_reader_id'] else False
        }
        rooms[room_name]['seats'].append(seat)

    # 当前用户今天的有效预订
    cursor.execute("""
        SELECT sb.booking_id, sb.seat_id, s.seat_number, r.name AS room_name,
               sb.start_time, sb.end_time
        FROM SeatBookings sb
        JOIN Seats s ON sb.seat_id = s.seat_id
        JOIN Rooms r ON s.room_id = r.room_id
        WHERE sb.reader_id = %s 
          AND sb.status = 'active'
          AND sb.end_time > NOW()
        ORDER BY sb.start_time DESC
        LIMIT 1
    """, (session['user_id'],))
    current_booking = cursor.fetchone()

    conn.close()

    return render_template('seats.html',
                           rooms=list(rooms.values()),
                           current_booking=current_booking)


# 预订座位（AJAX）
@app.route('/book_seat', methods=['POST'])
@login_required
def book_seat():
    seat_id = request.form.get('seat_id')
    duration_minutes = int(request.form.get('duration', 120))  # 默认2小时

    if not seat_id:
        return {'success': False, 'message': '无效的座位'}

    start_time = datetime.now()
    end_time = start_time + timedelta(minutes=duration_minutes)

    conn = get_db_connection()
    if not conn:
        return {'success': False, 'message': '数据库连接失败'}

    cursor = conn.cursor()

    try:
        # 检查座位是否已被预订（时间冲突）
        cursor.execute("""
            SELECT booking_id FROM SeatBookings 
            WHERE seat_id = %s 
              AND status = 'active'
              AND end_time > NOW()
        """, (seat_id,))
        if cursor.fetchone():
            return {'success': False, 'message': '该座位当前已被预订，请选择其他座位'}

        # 检查用户是否已有有效预订
        cursor.execute("""
            SELECT booking_id FROM SeatBookings 
            WHERE reader_id = %s 
              AND status = 'active'
              AND end_time > NOW()
        """, (session['user_id'],))
        if cursor.fetchone():
            return {'success': False, 'message': '您已有有效预订，不可重复预约！'}

        # 插入新预订
        cursor.execute("""
            INSERT INTO SeatBookings 
            (reader_id, seat_id, start_time, end_time, status)
            VALUES (%s, %s, %s, %s, 'active')
        """, (session['user_id'], seat_id, start_time, end_time))

        conn.commit()
        return {'success': True, 'message': f'预订成功！使用时间至 {end_time.strftime("%H:%M")}'}

    except Exception as e:
        conn.rollback()
        return {'success': False, 'message': '预订失败：' + str(e)}
    finally:
        conn.close()


# 取消预订
@app.route('/cancel_booking/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    conn = get_db_connection()
    if not conn:
        flash('数据库连接失败', 'danger')
        return redirect(url_for('seats'))

    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE SeatBookings 
            SET status = 'cancelled' 
            WHERE booking_id = %s 
              AND reader_id = %s 
              AND status = 'active'
        """, (booking_id, session['user_id']))

        if cursor.rowcount > 0:
            conn.commit()
            flash('已成功取消预订', 'success')
        else:
            flash('取消失败：无权限或预订已失效', 'danger')
    except Exception as e:
        conn.rollback()
        flash('操作失败', 'danger')
    finally:
        conn.close()

    return redirect(url_for('seats'))


# ==================== 登录 / 注册 / 密码找回 ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM Readers WHERE username = %s", (username,))
        user = cursor.fetchone()
        conn.close()

        # 【关键修改：直接明文对比，不要用 bcrypt】
        if user and user['password_hash'] == password:
            # 登录成功，创建 session
            session['user_id'] = user['reader_id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['name'] = user['name']
            flash('登录成功！欢迎 ' + user['name'], 'success')
            return redirect(url_for('index'))  # 或 dashboard

        else:
            flash('用户名或密码错误！', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    # 清除所有 session 数据
    session.clear()
    flash('您已成功退出登录', 'success')
    return redirect(url_for('login'))  # 跳转回登录页面

@app.route('/register', methods=['GET', 'POST'])
def register():
    # 支持通过 ?ref=XXX 自动填充邀请码
    prefill_ref = request.args.get('ref', '').strip().upper()

    if request.method == 'POST':
        name = request.form['name'].strip()
        username = request.form['username'].strip().lower()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        referral_code_input = request.form.get('referral_code', '').strip().upper()

        # 基础验证
        if not all([name, username, email, password]):
            flash('请填写所有必填项', 'danger')
            return render_template('register.html')

        if password != confirm_password:
            flash('两次密码不一致', 'danger')
            return render_template('register.html')

        if len(password) < 6:
            flash('密码至少6位', 'danger')
            return render_template('register.html')

        conn = get_db_connection()
        if not conn:
            flash('数据库连接失败', 'danger')
            return render_template('register.html')

        cursor = conn.cursor(dictionary=True)

        # 检查用户名或邮箱是否已存在
        cursor.execute("SELECT * FROM Readers WHERE username = %s OR email = %s", (username, email))
        if cursor.fetchone():
            flash('用户名或邮箱已被注册', 'danger')
            conn.close()
            return render_template('register.html')

        referrer_id = None
        if referral_code_input:
            cursor.execute("SELECT reader_id FROM Readers WHERE referral_code = %s", (referral_code_input,))
            referrer = cursor.fetchone()
            if referrer:
                referrer_id = referrer['reader_id']
            else:
                flash('邀请码无效', 'danger')
                conn.close()
                return render_template('register.html')

        try:
            # 1. 先插入用户信息（referral_code 暂时为空）
            initial_balance = Decimal('5.00') if referrer_id else Decimal('0.00')
            hashed = bcrypt.generate_password_hash(password).decode('utf-8')

            cursor.execute("""
                INSERT INTO Readers 
                (name, username, password_hash, email, role, balance, referrer_id)
                VALUES (%s, %s, %s, %s, 'student', %s, %s)
            """, (name, username, hashed, email, initial_balance, referrer_id))

            # 2. 获取刚刚插入的用户ID
            new_user_id = cursor.lastrowid

            # 3. 现在安全生成邀请码（基于真实ID）
            new_referral_code = (
                    chr(65 + (new_user_id % 26)) +
                    chr(65 + ((new_user_id * 7) % 26)) +
                    str(new_user_id).zfill(6)
            ).upper()

            # 4. 更新这条记录，把邀请码补上
            cursor.execute("""
                UPDATE Readers 
                SET referral_code = %s 
                WHERE reader_id = %s
            """, (new_referral_code, new_user_id))

            # 5. 如果有邀请人，给邀请人发奖励
            if referrer_id:
                cursor.execute("""
                    UPDATE Readers 
                    SET balance = balance + 10.00,
                        invited_count = invited_count + 1,
                        referral_reward = referral_reward + 10.00
                    WHERE reader_id = %s
                """, (referrer_id,))

            conn.commit()
            flash('注册成功！奖励已发放，请登录', 'success')
            conn.close()
            return redirect(url_for('login'))

        except Exception as e:
            conn.rollback()
            flash(f'注册失败：{str(e)}', 'danger')
            conn.close()
            return render_template('register.html')


        except Exception as e:
            conn.rollback()
            flash(f'注册失败：{str(e)}', 'danger')
            conn.close()
            return render_template('register.html')

    # GET 请求：显示注册页，支持预填邀请码
    return render_template('register.html')



@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email'].strip()
        if not email:
            flash('请输入邮箱', 'danger')
            return render_template('forgot_password.html')

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT reader_id FROM Readers WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user:
            token = secrets.token_urlsafe(32)
            expires = datetime.now() + timedelta(hours=1)
            cursor.execute("""
                UPDATE Readers SET reset_token = %s, reset_expires = %s
                WHERE reader_id = %s
            """, (token, expires, user['reader_id']))
            conn.commit()

            reset_url = url_for('reset_password', token=token, _external=True)
            print("\n" + "="*80)
            print("【密码重置链接 - 请复制到浏览器打开】")
            print(reset_url)
            print("="*80 + "\n")
            flash('重置密码链接已生成（查看终端输出）', 'info')
        else:
            flash('该邮箱未注册', 'danger')

        conn.close()

    return render_template('forgot_password.html')


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT reader_id, reset_expires FROM Readers WHERE reset_token = %s", (token,))
    user = cursor.fetchone()

    if not user or user['reset_expires'] < datetime.now():
        flash('链接无效或已过期', 'danger')
        conn.close()
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form['password']
        confirm = request.form['confirm_password']
        if password != confirm:
            flash('两次密码不一致', 'danger')
        elif len(password) < 6:
            flash('密码至少6位', 'danger')
        else:
            # 【关键修改】：直接存明文密码，不加密！
            cursor.execute("""
                UPDATE Readers 
                SET password_hash = %s, reset_token = NULL, reset_expires = NULL
                WHERE reader_id = %s
            """, (password, user['reader_id']))   # ← 直接传 password，不 hashed

            conn.commit()
            conn.close()
            flash('密码重置成功，请登录', 'success')
            return redirect(url_for('login'))

    conn.close()
    return render_template('reset_password.html', token=token)



# ==================== 原有路由（部分加登录保护） ====================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/books')
def books():
    search = request.args.get('search', '').strip()
    conn = get_db_connection()
    if not conn:
        return render_template('books.html', books=[], search=search)

    cursor = conn.cursor(dictionary=True)
    if search:
        sql = """
            SELECT b.book_id, b.title, b.author, p.publisher_name, c.category_name,
                   COUNT(bc.copy_id) AS total_copies,
                   COUNT(CASE WHEN bc.status = 'available' THEN 1 END) AS available_copies,
                   MAX(CASE WHEN bc.status = 'available' THEN bc.copy_id END) AS available_copy_id
            FROM Books b
            LEFT JOIN Publishers p ON b.publisher_id = p.publisher_id
            LEFT JOIN Categories c ON b.category_id = c.category_id
            LEFT JOIN BookCopies bc ON b.book_id = bc.book_id
            WHERE b.title LIKE %s OR b.author LIKE %s
            GROUP BY b.book_id ORDER BY b.title
        """
        cursor.execute(sql, (f'%{search}%', f'%{search}%'))
    else:
        sql = """
            SELECT b.book_id, b.title, b.author, p.publisher_name, c.category_name,
                   COUNT(bc.copy_id) AS total_copies,
                   COUNT(CASE WHEN bc.status = 'available' THEN 1 END) AS available_copies,
                   MAX(CASE WHEN bc.status = 'available' THEN bc.copy_id END) AS available_copy_id
            FROM Books b
            LEFT JOIN Publishers p ON b.publisher_id = p.publisher_id
            LEFT JOIN Categories c ON b.category_id = c.category_id
            LEFT JOIN BookCopies bc ON b.book_id = bc.book_id
            GROUP BY b.book_id ORDER BY b.title
        """
        cursor.execute(sql)
    books = cursor.fetchall()
    conn.close()
    return render_template('books.html', books=books, search=search)


@app.route('/borrow/<int:copy_id>')
@login_required
def borrow(copy_id):
    conn = get_db_connection()
    if not conn:
        return redirect(url_for('books'))

    cursor = conn.cursor()
    reader_id = session['user_id']  # 使用登录用户
    today = date.today()

    try:
        due_date = today.replace(month=today.month + 1)
    except ValueError:
        due_date = today.replace(year=today.year + 1, month=1)

    try:
        cursor.execute("SELECT status FROM BookCopies WHERE copy_id = %s FOR UPDATE", (copy_id,))
        result = cursor.fetchone()
        if not result or result[0] != 'available':
            flash('该副本不可借！', 'danger')
        else:
            cursor.execute("UPDATE BookCopies SET status = 'borrowed' WHERE copy_id = %s", (copy_id,))
            cursor.execute("""
                INSERT INTO BorrowRecords (reader_id, copy_id, borrow_date, due_date)
                VALUES (%s, %s, %s, %s)
            """, (reader_id, copy_id, today, due_date))
            conn.commit()
            flash(f'借书成功！', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'借书失败：{str(e)}', 'danger')
    finally:
        conn.close()

    return redirect(url_for('books'))

@app.route('/dashboard')
def dashboard():
    if not session.get('user_id'):
        flash('请先登录！', 'warning')
        return redirect(url_for('login'))

    conn = get_db_connection()   # ←←← 这里！必须是 get_db_connection()
    if not conn:
        flash('数据库连接失败', 'danger')
        return redirect(url_for('books'))

    cursor = conn.cursor(dictionary=True)
    user_id = session['user_id']

    # 获取用户信息（包含余额）
    cursor.execute("""
        SELECT name, username, email, role, balance,
               referral_code, invited_count, referral_reward
        FROM Readers 
        WHERE reader_id = %s
    """, (user_id,))
    user = cursor.fetchone()


    # 当前借阅中（未归还）
    cursor.execute("""
        SELECT b.title, b.author, br.borrow_date, br.due_date, br.record_id,
               DATEDIFF(CURDATE(), br.due_date) AS overdue_days
        FROM BorrowRecords br
        JOIN BookCopies bc ON br.copy_id = bc.copy_id
        JOIN Books b ON bc.book_id = b.book_id
        WHERE br.reader_id = %s AND br.return_date IS NULL
        ORDER BY br.due_date ASC
    """, (user_id,))
    current_borrows = cursor.fetchall()

    # 逾期数量
    overdue_count = len([item for item in current_borrows if item['overdue_days'] and item['overdue_days'] > 0])

    # 最近归还记录（最多10条）
    cursor.execute("""
        SELECT b.title, b.author, br.borrow_date, br.due_date, br.return_date
        FROM BorrowRecords br
        JOIN BookCopies bc ON br.copy_id = bc.copy_id
        JOIN Books b ON bc.book_id = b.book_id
        WHERE br.reader_id = %s AND br.return_date IS NOT NULL
        ORDER BY br.return_date DESC
        LIMIT 10
    """, (user_id,))
    history_borrows = cursor.fetchall()

    # 未支付罚款总额
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total_fine
        FROM Fines f
        JOIN BorrowRecords br ON f.record_id = br.record_id
        WHERE br.reader_id = %s AND f.paid = FALSE
    """, (user_id,))
    fine_result = cursor.fetchone()
    total_fine = fine_result['total_fine']

    conn.close()

    # 关键：直接用 user['balance'] 传给模板，不要用 current_balance
    return render_template('dashboard.html',
                          user=user,
                          current_borrows=current_borrows,
                          overdue_count=overdue_count,
                          history_borrows=history_borrows,
                          total_fine=total_fine,
                          balance=user['balance'])

# 在 app.py 新增路由
@app.route('/pay_fines')
def pay_fines():
    if not session.get('user_id'):
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    user_id = session['user_id']

    cursor.execute("SELECT balance FROM Readers WHERE reader_id = %s", (user_id,))
    balance = cursor.fetchone()['balance']

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total_due
        FROM Fines WHERE record_id IN (
            SELECT record_id FROM BorrowRecords WHERE reader_id = %s
        ) AND paid = FALSE
    """, (user_id,))
    total_due = cursor.fetchone()['total_due']

    if total_due == 0:
        flash('您没有未支付的罚款', 'info')
    elif balance >= total_due:
        # 扣余额 + 标记已支付
        cursor.execute("UPDATE Readers SET balance = balance - %s WHERE reader_id = %s", (total_due, user_id))
        cursor.execute("""
            UPDATE Fines SET paid = TRUE 
            WHERE record_id IN (SELECT record_id FROM BorrowRecords WHERE reader_id = %s) AND paid = FALSE
        """, (user_id,))
        conn.commit()
        flash(f'支付成功！扣除 ¥{total_due:.2f}，剩余余额 ¥{balance - total_due:.2f}', 'success')
    else:
        flash(f'余额不足！需 ¥{total_due:.2f}，当前仅 ¥{balance:.2f}', 'danger')

    conn.close()
    return redirect(url_for('dashboard'))


@app.route('/recharge', methods=['GET', 'POST'])
@login_required   # 建议加上这个装饰器，防止未登录访问
def recharge():
    conn = get_db_connection()
    if not conn:
        flash('数据库连接失败', 'danger')
        return redirect(url_for('dashboard'))

    cursor = conn.cursor(dictionary=True)
    user_id = session['user_id']

    # 获取当前余额（返回的是 Decimal 类型）
    cursor.execute("SELECT balance FROM Readers WHERE reader_id = %s", (user_id,))
    current_balance = cursor.fetchone()['balance']   # 类型：decimal.Decimal

    if request.method == 'POST':
        try:
            amount_str = request.form['amount'].strip()
            if not amount_str:
                flash('请输入充值金额', 'danger')
            else:
                amount = Decimal(amount_str)   # ←←← 关键：转成 Decimal
                if amount <= 0:
                    flash('充值金额必须大于0！', 'danger')
                elif amount > Decimal('10000'):
                    flash('单次充值不超过10000元', 'danger')
                else:
                    new_balance = current_balance + amount   # 现在可以安全相加了
                    cursor.execute(
                        "UPDATE Readers SET balance = %s WHERE reader_id = %s",
                        (new_balance, user_id)
                    )
                    conn.commit()
                    flash(f'充值成功！+¥{amount:.2f}，当前余额 ¥{new_balance:.2f}', 'success')
                    current_balance = new_balance   # 更新页面显示
        except Exception as e:
            flash(f'充值失败：{str(e)}', 'danger')
            conn.rollback()

    conn.close()
    return render_template('recharge.html', balance=current_balance)

@app.route('/return/<int:record_id>')
@login_required
def return_book(record_id):
    conn = get_db_connection()
    if not conn:
        return redirect(url_for('borrows'))

    cursor = conn.cursor()
    today = date.today()

    try:
        cursor.execute("""
            SELECT br.copy_id, br.due_date 
            FROM BorrowRecords br 
            WHERE br.record_id = %s AND br.return_date IS NULL
        """, (record_id,))
        record = cursor.fetchone()

        if not record:
            flash('记录不存在或已归还！', 'danger')
        else:
            copy_id, due_date = record

            # 计算逾期天数和罚款（每天5元）
            overdue_days = max(0, (today - due_date).days)
            fine_amount = overdue_days * 5.0

            # 更新副本状态、归还日期、罚款金额
            cursor.execute("UPDATE BookCopies SET status = 'available' WHERE copy_id = %s", (copy_id,))
            cursor.execute("""
                UPDATE BorrowRecords 
                SET return_date = %s, fine = %s 
                WHERE record_id = %s
            """, (today, fine_amount, record_id))

            conn.commit()

            if overdue_days > 0:
                flash(f'归还成功！逾期 {overdue_days} 天，产生罚款 ¥{fine_amount:.2f}', 'warning')
            else:
                flash('归还成功！无罚款', 'success')

    except Exception as e:
        conn.rollback()
        flash(f'还书失败：{str(e)}', 'danger')
    finally:
        conn.close()

    return redirect(url_for('borrows'))

@app.route('/pay_fine', methods=['POST'])
@login_required
def pay_fine():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 计算当前用户所有未支付罚款总额
        cursor.execute("""
            SELECT COALESCE(SUM(fine), 0) AS total_fine 
            FROM BorrowRecords 
            WHERE reader_id = %s AND fine > 0
        """, (user_id,))
        total_fine = cursor.fetchone()['total_fine']

        if total_fine <= 0:
            flash('您当前没有未支付的罚款', 'info')
            return redirect(url_for('dashboard'))

        # 获取用户当前余额
        cursor.execute("SELECT balance FROM Readers WHERE reader_id = %s", (user_id,))
        user = cursor.fetchone()
        current_balance = user['balance'] if user else 0.0

        if current_balance < total_fine:
            flash(f'余额不足！需支付 ¥{total_fine:.2f}，当前余额 ¥{current_balance:.2f}，请先充值', 'danger')
            return redirect(url_for('dashboard'))  # 后续可跳转到充值页

        # 扣款 + 清零罚款
        new_balance = current_balance - total_fine
        cursor.execute("UPDATE Readers SET balance = %s WHERE reader_id = %s", (new_balance, user_id))
        cursor.execute("UPDATE BorrowRecords SET fine = 0 WHERE reader_id = %s AND fine > 0", (user_id,))

        conn.commit()
        flash(f'支付成功！扣除 ¥{total_fine:.2f}，剩余余额 ¥{new_balance:.2f}', 'success')

    except Exception as e:
        conn.rollback()
        flash(f'支付失败：{str(e)}', 'danger')
    finally:
        conn.close()

    return redirect(url_for('dashboard'))


@app.route('/borrows')
def borrows():
    conn = get_db_connection()
    if not conn:
        return render_template('borrows.html', borrows=[])

    cursor = conn.cursor(dictionary=True)

    if session.get('user_id'):
        # 已登录：只看自己的
        cursor.execute("""
            SELECT br.record_id, r.name AS reader_name, b.title AS book_title,
                   br.borrow_date, br.due_date, br.return_date,
                   CASE 
                     WHEN br.return_date IS NOT NULL THEN '已归还'
                     WHEN br.due_date < CURDATE() THEN '逾期'
                     ELSE '借阅中'
                   END AS status
            FROM BorrowRecords br
            JOIN Readers r ON br.reader_id = r.reader_id
            JOIN BookCopies bc ON br.copy_id = bc.copy_id
            JOIN Books b ON bc.book_id = b.book_id
            WHERE br.reader_id = %s
            ORDER BY br.borrow_date DESC
        """, (session['user_id'],))
    else:
        # 未登录：看全部
        cursor.execute("""
            SELECT br.record_id, r.name AS reader_name, b.title AS book_title,
                   br.borrow_date, br.due_date, br.return_date,
                   CASE 
                     WHEN br.return_date IS NOT NULL THEN '已归还'
                     WHEN br.due_date < CURDATE() THEN '逾期'
                     ELSE '借阅中'
                   END AS status
            FROM BorrowRecords br
            JOIN Readers r ON br.reader_id = r.reader_id
            JOIN BookCopies bc ON br.copy_id = bc.copy_id
            JOIN Books b ON bc.book_id = b.book_id
            ORDER BY br.borrow_date DESC
            LIMIT 200
        """)

    borrows = cursor.fetchall()
    conn.close()
    return render_template('borrows.html', borrows=borrows)


@app.route('/overdue')
def overdue():
    conn = get_db_connection()
    if not conn:
        return render_template('overdue.html', overdue=[])

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM view_overdue ORDER BY overdue_days DESC")
    overdue = cursor.fetchall()
    conn.close()
    return render_template('overdue.html', overdue=overdue)


@app.route('/add_book', methods=['GET', 'POST'])
def add_book():
    # 这里可以加管理员权限判断，暂时开放
    conn = get_db_connection()
    if not conn:
        return redirect(url_for('books'))

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT category_id, category_name FROM Categories ORDER BY category_name")
    categories = cursor.fetchall()
    cursor.execute("SELECT publisher_id, publisher_name FROM Publishers ORDER BY publisher_name")
    publishers = cursor.fetchall()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        author = request.form.get('author', '').strip()
        isbn = request.form.get('isbn', '').strip()
        publish_year = request.form.get('publish_year') or None
        publisher_id = request.form.get('publisher_id') or None
        category_id = request.form.get('category_id') or None
        copies = int(request.form.get('copies', '1'))

        try:
            cursor.execute("""
                INSERT INTO Books (title, author, isbn, publish_year, publisher_id, category_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (title, author, isbn, publish_year, publisher_id, category_id))
            book_id = cursor.lastrowid
            for _ in range(copies):
                cursor.execute("INSERT INTO BookCopies (book_id, status) VALUES (%s, 'available')", (book_id,))
            conn.commit()
            flash('书籍添加成功！', 'success')
            return redirect(url_for('books'))
        except Exception as e:
            conn.rollback()
            flash(f'添加失败：{str(e)}', 'danger')

    conn.close()
    return render_template('add_book.html', categories=categories, publishers=publishers)


@app.route('/edit_book/<int:book_id>', methods=['GET', 'POST'])
def edit_book(book_id):
    conn = get_db_connection()
    if not conn:
        flash('数据库连接失败！', 'danger')
        return redirect(url_for('books'))

    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        title = request.form['title'].strip()
        author = request.form['author'].strip()
        isbn = request.form['isbn'].strip() or None
        publish_year = request.form['publish_year'] or None
        publish_year = int(publish_year) if publish_year else None
        publisher_id = request.form['publisher_id'] or None
        category_id = request.form['category_id'] or None

        if not title or not author:
            flash('书名和作者不能为空！', 'danger')
        else:
            try:
                cursor.execute("""
                    UPDATE Books 
                    SET title = %s, author = %s, isbn = %s, 
                        publish_year = %s, publisher_id = %s, category_id = %s
                    WHERE book_id = %s
                """, (title, author, isbn, publish_year, publisher_id, category_id, book_id))
                conn.commit()
                flash(f'《{title}》修改成功！', 'success')
                return redirect(url_for('books'))
            except Exception as e:
                conn.rollback()
                flash(f'修改失败：{str(e)}', 'danger')
                return redirect(url_for('edit_book', book_id=book_id))

    cursor.execute("""
        SELECT b.*, p.publisher_name, c.category_name 
        FROM Books b
        LEFT JOIN Publishers p ON b.publisher_id = p.publisher_id
        LEFT JOIN Categories c ON b.category_id = c.category_id
        WHERE b.book_id = %s
    """, (book_id,))
    book = cursor.fetchone()
    if not book:
        flash('书籍不存在', 'danger')
        return redirect(url_for('books'))

    cursor.execute("SELECT category_id, category_name FROM Categories ORDER BY category_name")
    categories = cursor.fetchall()
    cursor.execute("SELECT publisher_id, publisher_name FROM Publishers ORDER BY publisher_name")
    publishers = cursor.fetchall()
    conn.close()

    return render_template('edit_book.html', book=book, categories=categories, publishers=publishers)


@app.route('/delete_book/<int:book_id>')
def delete_book(book_id):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Books WHERE book_id = %s", (book_id,))
            conn.commit()
            flash('删除成功', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'删除失败：{str(e)}', 'danger')
        finally:
            conn.close()
    return redirect(url_for('books'))

@app.route('/admin')
def admin_dashboard():
    # 权限检查：只有 admin 才能访问
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('权限不足，只有管理员可以访问后台', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 1. 全站统计数据
    cursor.execute("SELECT COUNT(*) AS total_users FROM Readers")
    total_users = cursor.fetchone()['total_users']

    cursor.execute("SELECT COUNT(*) AS total_books FROM Books")
    total_books = cursor.fetchone()['total_books']

    # 【修改1】当前借阅数量：表名改为 BorrowRecords
    cursor.execute("SELECT COUNT(*) AS active_borrows FROM BorrowRecords WHERE return_date IS NULL")
    active_borrows = cursor.fetchone()['active_borrows']

    cursor.execute("SELECT COALESCE(SUM(balance), 0) AS total_balance FROM Readers")
    total_balance = cursor.fetchone()['total_balance']

    cursor.execute("SELECT COALESCE(SUM(referral_reward), 0) AS total_rewards FROM Readers")
    total_rewards = cursor.fetchone()['total_rewards']

    # 2. 邀请排行榜 TOP10
    cursor.execute("""
        SELECT name, username, invited_count, referral_reward 
        FROM Readers 
        ORDER BY invited_count DESC, referral_reward DESC 
        LIMIT 10
    """)
    ranking = cursor.fetchall()

    # 3. 用户列表（所有用户基本信息）
    cursor.execute("""
        SELECT reader_id, name, username, email, role, balance, 
               invited_count, referral_reward
        FROM Readers 
        ORDER BY reader_id
    """)
    all_users = cursor.fetchall()

    # 4. 最热门书籍 TOP5（已完全适配你的表结构）
    cursor.execute("""
        SELECT b.title, b.author, COUNT(*) AS borrow_count
        FROM BorrowRecords br
        JOIN BookCopies bc ON br.copy_id = bc.copy_id
        JOIN Books b ON bc.book_id = b.book_id
        GROUP BY b.book_id, b.title, b.author
        ORDER BY borrow_count DESC
        LIMIT 5
    """)
    hot_books = cursor.fetchall()


    conn.close()

    return render_template('admin.html',
                           total_users=total_users,
                           total_books=total_books,
                           active_borrows=active_borrows,
                           total_balance=total_balance,
                           total_rewards=total_rewards,
                           ranking=ranking,
                           all_users=all_users,
                           hot_books=hot_books)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)


