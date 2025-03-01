import logging
import requests
import re
import ddddocr
import os
import time

def setup_logger(name, verbose=False):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    if logger.handlers:
        logger.handlers.clear()
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)-10s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger

class Gamemale:
    def __init__(self, username, password, questionid='0', answer=None, verbose=False):
        self.verbose = verbose
        self.main_logger = setup_logger('GameMale', verbose)
        self.login_logger = setup_logger('登录', verbose)
        self.sign_logger = setup_logger('签到', verbose)
        self.exchange_logger = setup_logger('抽奖', verbose)
        
        self.login_logger.debug(f"当前用户: {username}")
        
        self.ocr = ddddocr.DdddOcr(show_ad=False)
        self.post_formhash = None
        self.sign_result = None
        self.exchange_result = None
        self.username = str(username)
        self.password = str(password)
        self.questionid = questionid
        self.answer = str(answer) if answer else ""
        self.hostname = "www.gamemale.com"
        self.session = requests.session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/91.0.4472.124 Safari/537.36'
            )
        })

    def get_login_formhash(self):
        url = f"https://{self.hostname}/member.php?mod=logging&action=login"
        self.login_logger.debug(f"登录页url: {url}")
        text = self.session.get(url).text
        loginhash_match = re.search(r'<div id="main_messaqge_(.+?)">', text)
        formhash_match = re.search(
            r'<input type="hidden" name="formhash" value="(.+?)" />',
            text
        )
        if not loginhash_match or not formhash_match:
            self.login_logger.debug(f"登录页:\n{text}")
            raise ValueError("无法获取 loginhash 或 formhash")
        loginhash = loginhash_match.group(1)
        formhash = formhash_match.group(1)
        self.login_logger.debug(f"已成功获取登录所需的 loginhash:'{loginhash}'，formhash:'{formhash}'")
        return loginhash, formhash

    def verify_code(self, max_retries=10) -> str:
        self.login_logger.info(f"看我 slay 验证码 [最多暗娼 {max_retries} 次惹]")
        
        for attempt in range(1, max_retries + 1):
            update_url = (
                f"https://{self.hostname}/misc.php?mod=seccode&action=update"
                f"&idhash=cSA&0.1234567&modid=member::logging"
            )
            self.login_logger.debug(f"正在从 {update_url} 获取请求验证码的必要参数")
            update_text = self.session.get(update_url).text
            update_match = re.search(r"update=(.+?)&idhash=", update_text)
            if not update_match:
                self.login_logger.debug(f"返回响应:\n{update_text}")
                continue
            update_val = update_match.group(1)
            code_url = (
                f"https://{self.hostname}/misc.php?mod=seccode&update="
                f"{update_val}&idhash=cSA"
            )
            self.login_logger.debug(f"正在从 {code_url} 获取验证码")
            headers = {
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Referer': f"https://{self.hostname}/member.php?mod=logging&action=login",
            }
            code_resp = self.session.get(code_url, headers=headers)
            if not code_resp.content:
                self.login_logger.debug(f"返回响应:\n{code_resp}")
                continue
                
            code = self.ocr.classification(code_resp.content)
            
            verify_url = (
                f"https://{self.hostname}/misc.php?mod=seccode&action=check&inajax=1&"
                f"modid=member::logging&idhash=cSA&secverify={code}"
            )
            self.login_logger.debug(f"正在向 {verify_url} 提交识别的验证码")
            res = self.session.get(verify_url).text
            if "succeed" in res:
                self.login_logger.info(f"识别成功: {code} (第{attempt}次)")
                return code
            else:
                self.login_logger.warning(f"错误的识别结果: {code} (第{attempt}次)")
        self.login_logger.error("超出最大重试次数，验证码识别失败")
        return ""

    def login(self) -> bool:
        self.login_logger.info(f"开始登录噜")
        
        code = self.verify_code()
        if not code:
            self.login_logger.error("缺少验证码，无法执行登录流程")
            return False
        loginhash, formhash = self.get_login_formhash()
        login_url = (
            f"https://{self.hostname}/member.php?mod=logging&action=login"
            f"&loginsubmit=yes&loginhash={loginhash}&inajax=1"
        )
        form_data = {
            'formhash': formhash,
            'referer': f"https://{self.hostname}/",
            'loginfield': self.username,
            'username': self.username,
            'password': self.password,
            'questionid': self.questionid,
            'answer': self.answer,
            'cookietime': 2592000,
            'seccodehash': 'cSA',
            'seccodemodid': 'member::logging',
            'seccodeverify': code,
        }
        
        self.login_logger.debug(f"正在向 {login_url} 提交登录表单")
        resp_text = self.session.post(login_url, data=form_data).text
        if "succeed" in resp_text:
            self.login_logger.info("登录成功")
            
            self.login_logger.debug(f"尝试访问论坛主页，以获取签到所需的 formhash")
            forum_url = f"https://{self.hostname}/forum.php"
            try:
                text = self.session.get(forum_url).text
                formhash_match = re.search(
                    r'<input type="hidden" name="formhash" value="(.+?)" />',
                    text
                )
                if formhash_match:
                    self.post_formhash = formhash_match.group(1)
                    self.login_logger.debug(f"formhash:'{self.post_formhash}'")
                else:
                    self.login_logger.warning("无法获取 formhash")
            except Exception as e:
                self.login_logger.error(f"访问论坛主页出错: {e}")
                
            return True
        else:
            self.login_logger.error("登录失败")
            self.login_logger.debug(f"原始响应:\n{resp_text}")
            return False

    def sign_gamemale(self):
        self.sign_logger.info("正在签到")
        if not self.post_formhash:
            self.sign_logger.warning("缺少 fromhash ，无法执行签到流程")
            return
        sign_url = (
            f"https://{self.hostname}/k_misign-sign.html?"
            f"operation=qiandao&format=button&formhash={self.post_formhash}"
        )
        try:
            self.sign_logger.debug(f"发送签到请求: {sign_url}")
            resp = self.session.get(sign_url)
            response_text = resp.text
            if response_text.startswith("<?xml"):
                cdata_start = response_text.find("<![CDATA[") + 9
                cdata_end = response_text.find("]]>")
                if cdata_start > 8 and cdata_end > cdata_start:
                    message = response_text[cdata_start:cdata_end]
                else:
                    message = response_text
            else:
                message = response_text
            self.sign_logger.debug(f"签到响应原始内容: {message}")
            if "签到成功" in message:
                sign_status = "签到成功，吸吸"
            elif "已签" in message:
                sign_status = "今日已签，可人"
            else:
                sign_status = "天啦噜，是未知状态"
            self.sign_result = {
                "site": "GameMale",
                "status": sign_status
            }
            self.sign_logger.info(f"结果: {sign_status}")
        except Exception as e:
            self.sign_logger.error(f"签到失败: {e}")
            self.sign_result = {
                "site": "GameMale",
                "status": "天啦噜，请求失败"
            }

    def daily_exchange(self):
        self.exchange_logger.info("正在参与卡片抽奖")
        if not self.post_formhash:
            self.exchange_logger.warning("未能获取 formhash，无法进行日常卡片抽奖")
            return
            
        timestamp = str(int(time.time() * 1000))
        exchange_url = (
            f"https://{self.hostname}/plugin.php?id=it618_award:ajax&ac=getaward"
            f"&formhash={self.post_formhash}&_={timestamp}"
        )
        headers = {
            'accept': 'application/json, text/javascript, /; q=0.01',
            'referer': f"https://{self.hostname}/it618_award-award.html",
            'x-requested-with': 'XMLHttpRequest',
        }
        try:
            self.exchange_logger.debug(f"发送抽奖请求: {exchange_url}")
            response = self.session.get(exchange_url, headers=headers)
            res_json = response.json()
            self.exchange_logger.debug(f"抽奖响应内容: {res_json}")
            
            if res_json.get("tipname") == "":
                exchange_status = "没有结果、可能今天已经抽过了"
            elif res_json.get("tipname") == "ok":
                exchange_status = f"成功，吸吸:\n{res_json.get('tipvalue')}"
            else:
                exchange_status = f"你好像进入了一个温暖潮湿的地方:\n{res_json}"
                
            self.exchange_result = {
                "site": "GameMale",
                "exchange_status": exchange_status
            }
            self.exchange_logger.info(f"结果: {exchange_status}")
        except Exception as e:
            self.exchange_logger.error(f"卡片抽奖失败: {e}")
            self.exchange_result = {
                "site": "GameMale",
                "exchange_status": "天啦噜，抽奖请求失败"
            }

    def run(self):
        self.main_logger.info("=== 全自动站街女 ===")
        if not self.login():
            return
        self.sign_gamemale()
        self.daily_exchange()
        
        self.main_logger.info("=== 今日站街成果 ===")
        if self.sign_result:
            self.main_logger.info(f"签到: {self.sign_result['status']}")
        if self.exchange_result:
            self.main_logger.info(f"抽奖: {self.exchange_result['exchange_status']}")

def main():
    username = os.getenv("USERNAME")
    password = os.getenv("PASSWORD")
    # questionid = os.getenv("QID")
    # answer = os.getenv("ANSWER")
    
    if not username or not password:
        logger = setup_logger("GameMale")
        logger.error("天啦噜，信息不全就想登录？")
        exit(1)
    gm = Gamemale(username, password, verbose=False)
    gm.run()

if __name__ == "__main__":
    main()
