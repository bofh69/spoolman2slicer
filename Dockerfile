FROM python:3.9.25-slim-trixie

COPY [".", "."]
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV SLICER=prusaslicer
RUN pip install -r requirements.txt
RUN mkdir -p /root/.config/spoolman2slicer
RUN cp -r ./templates-* /root/.config/spoolman2slicer/
RUN mkdir /configs
ENTRYPOINT [ "sh", "-c", "python3 ./spoolman2slicer.py -U -d /configs -s ${SLICER} -u ${SPOOLMAN_URL}" ]
