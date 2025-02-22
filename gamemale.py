import logging
import requests
import re
import ddddocr
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(filename)s %(funcName)s：line %(lineno)d %(levelname)s %(message)s"
)

class GamemaleNoCookie:
    def __init__(self, username, password, questionid='0', answer=None):
        self.ocr = ddddocr.DdddOcr(show_ad=False)
        self.post_formhash = None
        self.sign_result = None
        self.username = str(username)
        self.password = str(password)
        self.questionid = questionid
        self.answer = answer
        self.hostname = "www.gamemale.com"
        self.session = requests.session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/91.0.4472.124 Safari/537.36'
            )
        })

    # 访问登录页并解析出 loginhash 和 formhash
    def get_login_formhash(self):
        url = f"https://{self.hostname}/member.php?mod=logging&action=login"
        text = self.session.get(url).text

        loginhash_match = re.search(r'<div id="main_messaqge_(.+?)">', text)
        formhash_match = re.search(
            r'<input type="hidden" name="formhash" value="(.+?)" />',
            text
        )
        if not loginhash_match or not formhash_match:
            logging.debug(f"无法获取 loginhash 或 formhash 时的页面内容:\n{text}")
            raise ValueError("无法获取 loginhash 或 formhash")

        loginhash = loginhash_match.group(1)
        formhash = formhash_match.group(1)
        logging.info(f"已成功获取 loginhash 与 formhash")
        return loginhash, formhash

    # 获取并识别验证码
    def verify_code_once(self) -> str:
        update_url = (
            f"https://{self.hostname}/misc.php?mod=seccode&action=update"
            f"&idhash=cSA&0.1234567&modid=member::logging"
        )
        update_text = self.session.get(update_url).text
        update_match = re.search(r"update=(.+?)&idhash=", update_text)
        if not update_match:
            raise ValueError("无法匹配到验证码 update 参数")

        update_val = update_match.group(1)
        # 获取验证码图片
        code_url = (
            f"https://{self.hostname}/misc.php?mod=seccode&update="
            f"{update_val}&idhash=cSA"
        )
        headers = {
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Referer': f"https://{self.hostname}/member.php?mod=logging&action=login",
        }
        code_resp = self.session.get(code_url, headers=headers)

        # OCR 识别
        return self.ocr.classification(code_resp.content)

    # 多次尝试识别、提高成功率
    def verify_code(self, max_retries=10) -> str:
        for attempt in range(1, max_retries + 1):
            code = self.verify_code_once()
            verify_url = (
                f"https://{self.hostname}/misc.php?mod=seccode&action=check&inajax=1&"
                f"modid=member::logging&idhash=cSA&secverify={code}"
            )
            res = self.session.get(verify_url).text
            if "succeed" in res:
                logging.info(f"验证码识别成功 (第{attempt}次): {code}")
                return code
            else:
                logging.info(f"验证码识别失败 (第{attempt}次), 继续重试... code={code}")

        logging.error("验证码多次识别均失败")
        return ""

    # 登录
    def login_with_verify_code(self) -> bool:
        code = self.verify_code()
        if not code:
            logging.error("未能成功识别验证码，无法继续登录")
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
        resp_text = self.session.post(login_url, data=form_data).text
        if "succeed" in resp_text:
            logging.info("带验证码登录成功")
            return True

        logging.info("带验证码登录失败，请检查账号或密码是否正确")
        return False

    # 获取登录状态
    def login(self) -> bool:
        return self.login_with_verify_code()

    # 登录成功后，获取论坛主页的 formhash 用于签到
    def after_login_init(self):
        forum_url = f"https://{self.hostname}/forum.php"
        try:
            text = self.session.get(forum_url).text
            formhash_match = re.search(
                r'<input type="hidden" name="formhash" value="(.+?)" />',
                text
            )
            if formhash_match:
                self.post_formhash = formhash_match.group(1)
                logging.info(f"已成功获取论坛主页 formhash")
            else:
                logging.warning("未能在论坛主页获取到 formhash")
        except Exception as e:
            logging.error(f"访问论坛主页出错: {e}")

    def get_sign_hashcode(self) -> str:
        return self.post_formhash or ""

    # 签到
    def sign_gamemale(self):
        hashcode = self.get_sign_hashcode()
        if not hashcode:
            logging.warning("无法获取签到需要的 hashcode，跳过签到")
            return

        sign_url = (
            f"https://{self.hostname}/k_misign-sign.html?"
            f"operation=qiandao&format=button&formhash={hashcode}"
        )
        try:
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

            if "签到成功" in message:
                sign_status = "签到成功"
            elif "已签" in message:
                sign_status = "今日已签到"
            else:
                sign_status = "未知状态"

            print(f"=== 本次签到结果 ===\n{sign_status}")
            self.sign_result = {
                "site": "GameMale",
                "status": sign_status,
                # "message": message
            }
            logging.info(f"GameMale 签到结果: {sign_status}")

        except Exception as e:
            logging.error(f"GameMale 签到失败: {e}")
            self.sign_result = {
                "site": "GameMale",
                "status": "签到请求失败",
                # "message": str(e)
            }

    def run(self):
        if not self.login():
            logging.error("登录失败，流程终止")
            return

        self.after_login_init()
        self.sign_gamemale()
        # logging.info(f"GameMale 签到结果: {sign_status} | {message}") 
        logging.info(f"签到最终结果: {self.sign_result}")


if __name__ == "__main__":
    username = os.getenv("USERNAME")
    password = os.getenv("PASSWORD")
    # questionid = os.getenv("QID")
    # answer = os.getenv("ANSWER")

    if not username or not password:
        print("❌ 错误：未提供用户名或密码")
        exit(1)

    gm = GamemaleNoCookie(username, password)
    gm.run()
