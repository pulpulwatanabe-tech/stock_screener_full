import requests
import pandas as pd
from io import BytesIO

res = requests.get('https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls', timeout=15)
df = pd.read_excel(BytesIO(res.content), header=0)
print(df.columns.tolist())