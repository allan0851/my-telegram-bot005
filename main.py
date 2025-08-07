import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler
)
from functools import wraps



# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# 获取并验证token
token = os.getenv("BOT_TOKEN")
ADMIN_IDS = []

# 全局数据结构
orders_db = {}  # {chat_id: order_info}
financial_data = {
    'valid_orders': 0,
    'valid_amount': 0,
    'liquid_funds': 0,
    'new_clients': 0,
    'new_clients_amount': 0,
    'old_clients': 0,
    'old_clients_amount': 0,
    'interest': 0,
    'completed_orders': 0,
    'completed_amount': 0,
    'breach_orders': 0,
    'breach_amount': 0,
    'breach_end_orders': 0,
    'breach_end_amount': 0
}

# 按归属ID分组的数据
grouped_data = {}  # {group_id: {same structure as financial_data}}

# 订单ID计数器
order_counter = 0

# 星期分组映射
WEEKDAY_GROUP = {
    0: '一',  # Monday
    1: '二',  # Tuesday
    2: '三',  # Wednesday
    3: '四',  # Thursday
    4: '五',  # Friday
    5: '六',  # Saturday
    6: '日'   # Sunday
}


def admin_required(func):
    """检查用户是否是管理员的装饰器"""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        # 获取用户ID和聊天ID
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        ADMIN_IDS = [12345678]  # 替换为实际管理员ID

        if user_id not in ADMIN_IDS:
            await update.message.reply_text("⚠️ 此命令需要管理员权限")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


def private_chat_only(func):
    """检查是否在私聊中使用命令的装饰器"""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_chat.type != "private":
            await update.message.reply_text("⚠️ 此命令只能在私聊中使用")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


def get_current_group():
    """获取当前星期对应的分组"""
    today = date.today().weekday()
    return WEEKDAY_GROUP[today]


def generate_order_id():
    """生成订单ID"""
    global order_counter
    order_counter += 1
    return f"{order_counter:04d}"


def update_grouped_data(group_id, field, amount):
    """更新分组数据"""
    if group_id not in grouped_data:
        grouped_data[group_id] = {
            'valid_orders': 0,
            'valid_amount': 0,
            'liquid_funds': 0,
            'new_clients': 0,
            'new_clients_amount': 0,
            'old_clients': 0,
            'old_clients_amount': 0,
            'completed_orders': 0,
            'completed_amount': 0,
            'breach_orders': 0,
            'breach_amount': 0,
            'breach_end_orders': 0,
            'breach_end_amount': 0,
            'interest': 0
        }

    grouped_data[group_id][field] += amount


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """发送欢迎消息"""
    await update.message.reply_text(
        "欢迎使用订单管理系统！\n"
        "使用 /create <归属ID> <客户A/B> <金额> 创建新订单\n"
        "快捷操作：\n"
        "+<金额>b - 本金减少\n"
        "+<金额>c - 违约协商还款\n"
        "+<金额> - 利息收入\n"
        "状态变更：\n"
        "/normal - 转为正常状态\n"
        "/overdue - 转为逾期状态\n"
        "/end - 标记订单为完成\n"
        "/breach - 标记为违约\n"
        "/breach_end - 违约订单完成\n"
        "/report - 查看报表"
    )


async def create_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """创建新订单"""
    chat_id = update.message.chat_id

    # 检查群组是否已有订单
    if chat_id in orders_db:
        await update.message.reply_text("本群已有一个订单，请先完成或违约当前订单后再创建新订单。")
        return

    # 验证参数
    if len(context.args) != 3:
        await update.message.reply_text("用法: /create <归属ID> <客户A/B> <金额>")
        return

    group_id, customer, amount = context.args

    # 验证归属ID格式
    if len(group_id) != 3 or not group_id[0].isalpha() or not group_id[1:].isdigit():
        await update.message.reply_text("归属ID格式错误，应为1个字母加2个数字（如S01）")
        return

    # 验证客户类型
    customer = customer.upper()
    if customer not in ('A', 'B'):
        await update.message.reply_text("客户类型错误，应为A或B")
        return

    # 验证金额
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("金额必须为正数")
        return

    # 创建订单
    order_id = generate_order_id()
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    group = get_current_group()

    new_order = {
        'order_id': order_id,
        'group_id': group_id,
        'chat_id': chat_id,
        'date': current_date,
        'group': group,
        'customer': customer,
        'amount': amount,
        'state': 'normal'
    }

    # 保存订单
    orders_db[chat_id] = new_order

    # 更新财务数据
    financial_data['valid_orders'] += 1
    financial_data['valid_amount'] += amount
    financial_data['liquid_funds'] -= amount

    if customer == 'A':
        financial_data['new_clients'] += 1
        financial_data['new_clients_amount'] += amount
    else:
        financial_data['old_clients'] += 1
        financial_data['old_clients_amount'] += amount

    # 更新分组数据
    update_grouped_data(group_id, 'valid_orders', 1)
    update_grouped_data(group_id, 'valid_amount', amount)
    if customer == 'A':
        update_grouped_data(group_id, 'new_clients', 1)
        update_grouped_data(group_id, 'new_clients_amount', amount)
    else:
        update_grouped_data(group_id, 'old_clients', 1)
        update_grouped_data(group_id, 'old_clients_amount', amount)

    await update.message.reply_text(
        f"订单创建成功！\n"
        f"订单ID: {order_id}\n"
        f"归属ID: {group_id}\n"
        f"日期: {current_date}\n"
        f"分组: {group}\n"
        f"客户: {customer}\n"
        f"金额: {amount:.2f}\n"
        f"状态: normal"
    )


async def handle_amount_operation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理金额操作"""
    chat_id = update.message.chat_id
    text = update.message.text

    # 检查是否有订单
    if chat_id not in orders_db:
        await update.message.reply_text("本群没有订单，请先创建订单")
        return

    order = orders_db[chat_id]

    # 解析金额和操作类型
    try:
        if not text.startswith('+'):
            return  # 金额前没有加号，机器人不反应

        # 去掉加号后的文本
        amount_text = text[1:]

        if amount_text.endswith('b'):
            # 本金减少
            amount = float(amount_text[:-1])
            await process_principal_reduction(update, order, amount)
        elif amount_text.endswith('c'):
            # 违约协商还款
            amount = float(amount_text[:-1])
            await process_breach_payment(update, order, amount)
        else:
            # 利息收入
            amount = float(amount_text)
            await process_interest(update, order, amount)
    except ValueError:
        await update.message.reply_text("金额格式错误")


async def process_principal_reduction(update: Update, order: dict, amount: float):
    """处理本金减少"""
    if order['state'] not in ('normal', 'overdue'):
        await update.message.reply_text("当前订单状态不支持本金减少操作")
        return

    if amount <= 0 or amount > order['amount']:
        await update.message.reply_text("金额无效，必须大于0且不超过订单金额")
        return

    # 更新订单
    order['amount'] -= amount
    group_id = order['group_id']

    # 更新财务数据
    financial_data['valid_amount'] -= amount
    financial_data['completed_amount'] += amount
    financial_data['liquid_funds'] += amount

    # 更新分组数据
    update_grouped_data(group_id, 'valid_amount', -amount)
    update_grouped_data(group_id, 'completed_amount', amount)

    await update.message.reply_text(
        f"本金减少成功！\n"
        f"订单ID: {order['order_id']}\n"
        f"减少金额: {amount:.2f}\n"
        f"剩余金额: {order['amount']:.2f}"
    )


async def process_breach_payment(update: Update, order: dict, amount: float):
    """处理违约协商还款"""
    if order['state'] != 'breach':
        await update.message.reply_text("只有违约状态的订单才能进行协商还款")
        return

    if amount <= 0:
        await update.message.reply_text("金额无效，必须大于0")
        return

    # 更新订单
    order['amount'] -= amount
    group_id = order['group_id']

    # 更新财务数据
    financial_data['breach_end_amount'] += amount
    financial_data['liquid_funds'] += amount

    # 更新分组数据
    update_grouped_data(group_id, 'breach_end_amount', amount)

    await update.message.reply_text(
        f"违约协商还款成功！\n"
        f"订单ID: {order['order_id']}\n"
        f"还款金额: {amount:.2f}\n"
        f"剩余金额: {order['amount']:.2f}"
    )


async def process_interest(update: Update, order: dict, amount: float):
    """处理利息收入"""
    if amount <= 0:
        await update.message.reply_text("金额必须大于0")
        return

    # 更新财务数据
    financial_data['interest'] += amount
    financial_data['liquid_funds'] += amount

    # 更新分组数据
    update_grouped_data(order['group_id'], 'interest', amount)

    await update.message.reply_text(
        f"利息收入记录成功！\n"
        f"金额: {amount:.2f}\n"
        f"当前总利息: {financial_data['interest']:.2f}"
    )


async def set_normal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """转为正常状态"""
    chat_id = update.message.chat_id

    if chat_id not in orders_db:
        await update.message.reply_text("本群没有订单")
        return

    order = orders_db[chat_id]

    if order['state'] != 'overdue':
        await update.message.reply_text("只有逾期状态的订单才能转为正常状态")
        return

    order['state'] = 'normal'
    await update.message.reply_text(
        f"订单状态已更新为正常\n"
        f"订单ID: {order['order_id']}\n"
        f"当前状态: normal"
    )


async def set_overdue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """转为逾期状态"""
    chat_id = update.message.chat_id

    if chat_id not in orders_db:
        await update.message.reply_text("本群没有订单")
        return

    order = orders_db[chat_id]

    if order['state'] != 'normal':
        await update.message.reply_text("只有正常状态的订单才能转为逾期")
        return

    order['state'] = 'overdue'
    await update.message.reply_text(
        f"订单状态已更新为逾期\n"
        f"订单ID: {order['order_id']}\n"
        f"当前状态: overdue"
    )


async def set_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """标记订单为完成"""
    chat_id = update.message.chat_id

    if chat_id not in orders_db:
        await update.message.reply_text("本群没有订单")
        return

    order = orders_db[chat_id]

    if order['state'] not in ('normal', 'overdue'):
        await update.message.reply_text("只有正常或逾期状态的订单才能标记为完成")
        return

    # 更新订单状态
    order['state'] = 'end'
    group_id = order['group_id']
    amount = order['amount']

    # 更新财务数据
    financial_data['valid_orders'] -= 1
    financial_data['valid_amount'] -= amount
    financial_data['completed_orders'] += 1
    financial_data['completed_amount'] += amount
    financial_data['liquid_funds'] += amount

    # 更新分组数据
    update_grouped_data(group_id, 'valid_orders', -1)
    update_grouped_data(group_id, 'valid_amount', -amount)
    update_grouped_data(group_id, 'completed_orders', 1)
    update_grouped_data(group_id, 'completed_amount', amount)

    await update.message.reply_text(
        f"订单已完成！\n"
        f"订单ID: {order['order_id']}\n"
        f"完成金额: {amount:.2f}"
    )

    # 完成订单后从当前群组移除（可以创建新订单）
    del orders_db[chat_id]


async def set_breach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """标记为违约"""
    chat_id = update.message.chat_id

    if chat_id not in orders_db:
        await update.message.reply_text("本群没有订单")
        return

    order = orders_db[chat_id]

    if order['state'] != 'overdue':
        await update.message.reply_text("只有逾期状态的订单才能标记为违约")
        return

    # 更新订单状态
    order['state'] = 'breach'
    group_id = order['group_id']
    amount = order['amount']

    # 更新财务数据
    financial_data['valid_orders'] -= 1
    financial_data['valid_amount'] -= amount
    financial_data['breach_orders'] += 1
    financial_data['breach_amount'] += amount

    # 更新分组数据
    update_grouped_data(group_id, 'valid_orders', -1)
    update_grouped_data(group_id, 'valid_amount', -amount)
    update_grouped_data(group_id, 'breach_orders', 1)
    update_grouped_data(group_id, 'breach_amount', amount)

    await update.message.reply_text(
        f"订单已标记为违约！\n"
        f"订单ID: {order['order_id']}\n"
        f"违约金额: {amount:.2f}"
    )


async def set_breach_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """违约订单完成"""
    chat_id = update.message.chat_id

    if chat_id not in orders_db:
        await update.message.reply_text("本群没有订单")
        return

    order = orders_db[chat_id]

    if order['state'] != 'breach':
        await update.message.reply_text("只有违约状态的订单才能标记为违约完成")
        return

    # 更新订单状态
    order['state'] = 'breach_end'
    group_id = order['group_id']

    # 更新财务数据
    financial_data['breach_end_orders'] += 1

    # 更新分组数据
    update_grouped_data(group_id, 'breach_end_orders', 1)

    await update.message.reply_text(
        f"违约订单已完成！\n"
        f"订单ID: {order['order_id']}\n"
        f"状态: breach_end"
    )

    # 完成订单后从当前群组移除（可以创建新订单）
    del orders_db[chat_id]


async def show_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示报表"""
    # 检查是否有参数（特定归属ID的报表）
    if context.args:
        group_id = context.args[0]
        if group_id in grouped_data:
            data = grouped_data[group_id]
            report_type = f"归属ID {group_id} 的报表"
        else:
            await update.message.reply_text(f"找不到归属ID {group_id} 的数据")
            return
    else:
        data = financial_data
        report_type = "全局报表"

    # 生成报表文本
    report = (
        f"=== {report_type} ===\n"
        f"有效订单数: {data['valid_orders']}\n"
        f"有效订单金额: {data['valid_amount']:.2f}\n"
        f"活动资金: {data['liquid_funds']:.2f}\n"
        f"新客户数: {data['new_clients']}\n"
        f"新客户金额: {data['new_clients_amount']:.2f}\n"
        f"老客户数: {data['old_clients']}\n"
        f"老客户金额: {data['old_clients_amount']:.2f}\n"
        f"利息收入: {data['interest']:.2f}\n"
        f"完成订单数: {data['completed_orders']}\n"
        f"完成订单金额: {data['completed_amount']: .2f}\n"
        f"违约订单数: {data['breach_orders']}\n"
        f"违约订单金额: {data['breach_amount']:.2f}\n"
        f"违约完成订单数: {data['breach_end_orders']}\n"
        f"违约完成金额: {data['breach_end_amount']:.2f}\n"
    )

    # 添加键盘按钮用于查看分组报表
    if not context.args:  # 如果是全局报表，才显示分组按钮
        keyboard = []
        for group_id in sorted(grouped_data.keys()):
            keyboard.append([InlineKeyboardButton(
                f"查看 {group_id} 报表", callback_data=f"report_{group_id}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(report, reply_markup=reply_markup)
    else:
        await update.message.reply_text(report)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮回调"""
    query = update.callback_query
    await query.answer()

    if query.data.startswith("report_"):
        group_id = query.data[7:]
        if group_id in grouped_data:
            data = grouped_data[group_id]
            report = (
                f"=== 归属ID {group_id} 的报表 ===\n"
                f"有效订单数: {data['valid_orders']}\n"
                f"有效订单金额: {data['valid_amount']:.2f}\n"
                f"新客户数: {data['new_clients']}\n"
                f"新客户金额: {data['new_clients_amount']:.2f}\n"
                f"老客户数: {data['old_clients']}\n"
                f"老客户金额: {data['old_clients_amount']:.2f}\n"
                f"利息收入: {data['interest']:.2f}\n"
                f"完成订单数: {data['completed_orders']}\n"
                f"完成订单金额: {data['completed_amount']:.2f}\n"
                f"违约订单数: {data['breach_orders']}\n"
                f"违约订单金额: {data['breach_amount']:.2f}\n"
                f"违约完成订单数: {data['breach_end_orders']}\n"
                f"违约完成金额: {data['breach_end_amount']:.2f}\n"
            )
            await query.edit_message_text(text=report)
        else:
            await query.edit_message_text(text=f"找不到归属ID {group_id} 的数据")


async def show_current_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示当前订单状态"""
    chat_id = update.message.chat_id

    if chat_id not in orders_db:
        await update.message.reply_text("本群没有订单")
        return

    order = orders_db[chat_id]
    await update.message.reply_text(
        f"当前订单状态:\n"
        f"订单ID: {order['order_id']}\n"
        f"归属ID: {order['group_id']}\n"
        f"创建日期: {order['date']}\n"
        f"分组: {order['group']}\n"
        f"客户类型: {order['customer']}\n"
        f"当前金额: {order['amount']:.2f}\n"
        f"状态: {order['state']}"
    )


def main() -> None:
    """启动机器人"""
    # 创建Application并传入bot的token
    application = Application.builder().token(token).build()

    # 添加命令处理器（按新需求修改）
    application.add_handler(CommandHandler(
        "start", private_chat_only(admin_required(start))))
    application.add_handler(CommandHandler(
        "report", private_chat_only(admin_required(show_report))))

    # 其他需要管理员权限的命令
    application.add_handler(CommandHandler(
        "create", admin_required(create_order)))
    application.add_handler(CommandHandler(
        "normal", admin_required(set_normal)))
    application.add_handler(CommandHandler(
        "overdue", admin_required(set_overdue)))
    application.add_handler(CommandHandler("end", admin_required(set_end)))
    application.add_handler(CommandHandler(
        "breach", admin_required(set_breach)))
    application.add_handler(CommandHandler(
        "breach_end", admin_required(set_breach_end)))

    # 添加消息处理器（金额操作）
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, admin_required(handle_amount_operation)))

    # 添加回调查询处理器
    application.add_handler(CallbackQueryHandler(
        admin_required(button_callback)))

    # 启动机器人
    application.run_polling()


if __name__ == "__main__":
    main()
