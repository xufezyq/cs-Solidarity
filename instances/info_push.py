"""
信息推送实例
实现定时推送金价、股票、新闻等信息到指定微信群/个人
"""
import time
import json
import logging
import requests
import schedule
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from core.base_instance import BaseInstance
from core.wechat_instance import send_message as wx_send_message

log = logging.getLogger(__name__)


class InfoPush(BaseInstance):
    """信息推送实例：定时推送金价、股票、新闻等信息"""

    def __init__(self,
                 wechat_groups: List[str] = None,
                 push_times: List[str] = None,
                 group_configs: Dict[str, Dict] = None,
                 api_configs: Dict[str, Any] = None,
                 retry_count: int = 3,
                 retry_interval: int = 60,
                 debug: bool = False):
        self.wechat_groups = []
        if wechat_groups:
            if isinstance(wechat_groups, list):
                self.wechat_groups = wechat_groups
            else:
                self.wechat_groups = [wechat_groups]
        else:
            self.wechat_groups = ['文件传输助手']

        self.push_times = push_times or ["08:00"]
        self.group_configs = group_configs or {}
        self.api_configs = api_configs or {}
        self.retry_count = retry_count
        self.retry_interval = retry_interval
        self.debug = debug

        self.gold_price_cache = {}
        self.stock_cache = {}
        self.news_cache = []
        self._last_gold_fetch = 0
        self._last_stock_fetch = {}  # 每只股票独立时间戳
        self._last_news_fetch = 0

    def fetch_gold_price(self) -> Optional[Dict]:
        """获取金价数据"""
        try:
            current_time = time.time()
            if self.gold_price_cache and (current_time - self._last_gold_fetch) < 300:
                log.debug("[InfoPush] 使用金价缓存数据")
                return self.gold_price_cache

            api_key = self.api_configs.get('gold_api_key', '')
            if api_key:
                url = f"https://gold-api.cn/api/v1/gold/realtime?api_key={api_key}&variety=Au9999"
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()

                if data.get('code') == '0' or data.get('success') == '1':
                    if 'result' in data and 'dtList' in data['result']:
                        dt_list = data['result']['dtList']
                        for key in dt_list:
                            item = dt_list[key]
                            gold_data = {
                                'price': float(item.get('lastPrice', 0)),
                                'currency': 'CNY',
                                'unit': '克',
                                'change': float(item.get('changePrice', 0)),
                                'change_percent': float(item.get('changeMargin', '0%').replace('%', '')),
                                'update_time': item.get('updateTime', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                            }
                            break
                    elif 'data' in data:
                        gold_data = {
                            'price': float(data.get('data', {}).get('price', 0)),
                            'currency': 'CNY',
                            'unit': '克',
                            'change': float(data.get('data', {}).get('change', 0)),
                            'change_percent': float(data.get('data', {}).get('changePercent', 0)),
                            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                    else:
                        log.error(f"[InfoPush] 金价 API 返回数据格式未知：{data}")
                        return None
                else:
                    log.error(f"[InfoPush] 金价 API 返回错误：{data.get('msg', data.get('message', '未知错误'))}")
                    return None
            else:
                log.warning("[InfoPush] 未配置金价 API Key，跳过金价获取")
                return None

            self.gold_price_cache = gold_data
            self._last_gold_fetch = current_time
            log.debug(f"[InfoPush] 获取金价成功：{gold_data['price']} 元/克")
            return gold_data

        except Exception as e:
            log.error(f"[InfoPush] 获取金价失败：{e}")
            return None

    def fetch_stock_data(self, stock_codes: List[str] = None) -> List[Dict]:
        """获取股票数据"""
        if not stock_codes:
            stock_codes = self.api_configs.get('stock_codes', [])
        if not stock_codes:
            return []

        results = []
        for code in stock_codes:
            try:
                current_time = time.time()
                cache_key = f"stock_{code}"
                last_fetch = self._last_stock_fetch.get(code, 0)
                if cache_key in self.stock_cache and (current_time - last_fetch) < 600:
                    log.debug(f"[InfoPush] 使用股票 {code} 缓存数据")
                    results.append(self.stock_cache[cache_key])
                    continue

                market = "sh" if code.startswith('6') or code.startswith('9') else "sz"
                url = f"http://hq.sinajs.cn/list={market}{code}"
                response = requests.get(url, timeout=10)
                response.raise_for_status()

                stock_data = self._parse_stock_response(response.text, code)
                if stock_data:
                    results.append(stock_data)
                    self.stock_cache[cache_key] = stock_data
                    self._last_stock_fetch[code] = current_time
                    log.debug(f"[InfoPush] 获取股票 {code} 成功")

            except Exception as e:
                log.error(f"[InfoPush] 获取股票 {code} 失败：{e}")
                results.append({
                    'code': code, 'name': '获取失败', 'price': 0,
                    'change': 0, 'change_percent': 0, 'error': str(e)
                })

        return results

    def _parse_stock_response(self, response_text: str, code: str) -> Optional[Dict]:
        """解析股票 API 响应"""
        try:
            if '=' in response_text:
                parts = response_text.split('=')
                if len(parts) >= 2:
                    content = parts[1].strip().strip('"')
                    fields = content.split(',')
                    if len(fields) >= 4:
                        name = fields[0]
                        current_price = float(fields[3]) if fields[3] else 0
                        last_close = float(fields[2]) if fields[2] else 0
                        change = current_price - last_close
                        change_percent = (change / last_close * 100) if last_close else 0
                        return {
                            'code': code, 'name': name, 'price': current_price,
                            'change': change, 'change_percent': change_percent,
                            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
        except Exception as e:
            log.error(f"[InfoPush] 解析股票数据失败：{e}")
        return None

    def fetch_news(self) -> List[Dict]:
        """获取新闻数据"""
        try:
            current_time = time.time()
            if self.news_cache and (current_time - self._last_news_fetch) < 900:
                log.debug("[InfoPush] 使用新闻缓存数据")
                return self.news_cache

            backup_news = self.api_configs.get('backup_news', [])
            if backup_news:
                news_list = backup_news[:5]
                self.news_cache = news_list
                self._last_news_fetch = current_time
                log.debug(f"[InfoPush] 使用备用新闻，共 {len(news_list)} 条")
                return news_list

            return []

        except Exception as e:
            log.error(f"[InfoPush] 获取新闻失败：{e}")
            return []

    def format_message(self, group_name: str = None) -> str:
        """格式化推送消息"""
        group_config = self.group_configs.get(group_name, {})
        enable_gold = group_config.get('enable_gold', True)
        enable_stock = group_config.get('enable_stock', True)
        enable_news = group_config.get('enable_news', True)

        message_parts = []
        message_parts.append(f"【信息早报】{datetime.now().strftime('%Y年%m月%d日 %H:%M')}")
        message_parts.append("=" * 40)

        if enable_gold:
            gold_data = self.fetch_gold_price()
            if gold_data:
                change_symbol = "↑" if gold_data['change'] >= 0 else "↓"
                message_parts.append(f"💰 金价：{gold_data['price']} {gold_data['currency']}/{gold_data['unit']}")
                message_parts.append(f"   {change_symbol} {abs(gold_data['change']):.2f} ({abs(gold_data['change_percent']):.2f}%)")
                message_parts.append("")

        if enable_stock:
            stock_codes = group_config.get('stock_codes', self.api_configs.get('stock_codes', []))
            if stock_codes:
                stock_data_list = self.fetch_stock_data(stock_codes)
                if stock_data_list:
                    message_parts.append("📈 股票行情：")
                    for stock in stock_data_list:
                        if 'error' in stock:
                            message_parts.append(f"   {stock['code']}: {stock.get('error', '获取失败')}")
                        else:
                            change_symbol = "↑" if stock['change'] >= 0 else "↓"
                            message_parts.append(
                                f"   {stock['name']}({stock['code']}): {stock['price']:.2f} "
                                f"{change_symbol}{abs(stock['change']):.2f}({abs(stock['change_percent']):.2f}%)"
                            )
                    message_parts.append("")

        if enable_news:
            news_list = self.fetch_news()
            if news_list:
                message_parts.append("📰 每日新闻：")
                for idx, news in enumerate(news_list, 1):
                    message_parts.append(f"   {idx}. {news['title']}")
                    if news.get('summary'):
                        message_parts.append(f"      {news['summary'][:50]}...")
                message_parts.append("")

        message_parts.append("=" * 40)
        message_parts.append(f"更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        return "\n".join(message_parts)

    def send_message(self, message: str):
        """发送消息到所有配置的群（走 wechat_instance.send_message 确保一致）"""
        if not message or not message.strip():
            log.debug("[InfoPush] 消息为空，跳过发送")
            return

        log.debug(f"[InfoPush] 开始发送消息到 {len(self.wechat_groups)} 个群组/个人")
        for group in self.wechat_groups:
            try:
                wx_send_message(message, group)
                log.info(f"[InfoPush] 消息已发送到：{group}")
            except Exception as e:
                log.error(f"[InfoPush] 发送消息到 {group} 失败：{e}")

    def push_to_all_groups(self):
        """向所有群聊推送消息"""
        log.info("[InfoPush] 开始推送消息到所有群聊")
        group_name = self.wechat_groups[0] if self.wechat_groups else None
        message = self.format_message(group_name)
        self.send_message(message)
        log.info("[InfoPush] 推送完成")

    def start(self):
        """启动定时推送任务"""
        if self.debug:
            log.info("[InfoPush] DEBUG 模式，立即推送一次")
            self.push_to_all_groups()
            time.sleep(2)
            return

        log.info(f"[InfoPush] 启动，计划推送时间：{', '.join(self.push_times)}")
        for push_time in self.push_times:
            schedule.every().day.at(push_time).do(self.push_to_all_groups)
            log.debug(f"[InfoPush] 已注册定时任务：{push_time}")

        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("[InfoPush] 程序已停止")

    @classmethod
    def create_from_config(cls, config_path: str):
        """从配置文件创建实例"""
        if not Path(config_path).exists():
            raise FileNotFoundError(f"配置文件 {config_path} 不存在")
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return cls(
            wechat_groups=config.get('wechat_groups', ['文件传输助手']),
            push_times=config.get('push_times', ['08:00']),
            group_configs=config.get('group_configs', {}),
            api_configs=config.get('api_configs', {}),
            retry_count=config.get('retry_count', 3),
            retry_interval=config.get('retry_interval', 60),
            debug=config.get('debug', False)
        )

    @classmethod
    def create_from_data(cls, data: dict):
        """从字典数据创建实例"""
        if not isinstance(data, dict):
            raise TypeError("InfoPush.create_from_data 需要传入字典数据")

        # 从主配置读取 debug_mode
        debug_mode = False
        try:
            if 'config' in data:
                cfg_path = Path(data['config'])
                if cfg_path.parent.name == 'instconfig':
                    main_cfg_path = cfg_path.parent.parent / 'config.json'
                else:
                    main_cfg_path = cfg_path.parent / 'config.json'
            else:
                main_cfg_path = Path('config.json')
            with open(main_cfg_path, 'r', encoding='utf-8') as f:
                master_config = json.load(f)
                debug_mode = master_config.get('debug_mode', False)
        except Exception:
            pass

        if 'config' in data:
            config_path = data['config']
            if not Path(config_path).exists():
                raise FileNotFoundError(f"配置文件 {config_path} 不存在")
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            config = data

        return cls(
            wechat_groups=config.get("wechat_groups", []),
            push_times=config.get("push_times", ["08:00"]),
            group_configs=config.get("group_configs", {}),
            api_configs=config.get("api_configs", {}),
            retry_count=config.get("retry_count", 3),
            retry_interval=config.get("retry_interval", 60),
            debug=debug_mode or config.get("debug", False)
        )
