from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType
import os

os.environ['WDM_ARCH'] = '64'

opts = Options()
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-dev-shm-usage')
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=opts)
driver.get('https://www.wootit.com/adventistacademy/login/')
print('TITULO:', driver.title)
input('Presiona Enter para cerrar...')
driver.quit()
