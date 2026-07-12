# 這個 Dockerfile 用來把 ShuyuLendingBot 打包成容器映像檔
# 方便之後部署到 Linux 主機或 Podman 環境中執行

FROM docker.io/library/python:3.11-slim

WORKDIR /app

# 複製依賴清單並安裝套件
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 複製整個專案程式碼進容器
COPY . ./

# 讓 Python 輸出直接印到終端機，方便 Podman 收集 log
ENV PYTHONUNBUFFERED=1

# 啟動主程式
CMD ["python", "main.py"]