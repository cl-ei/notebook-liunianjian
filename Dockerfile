FROM python:3.11.2

EXPOSE 10091

ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
RUN echo 'export LANG="C.UTF-8"' >> /etc/profile

ENV RUN_ENV prod
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . ./

CMD ["python", "run.py"]
