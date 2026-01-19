# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

FROM python:3.10-slim

COPY [".", "."]
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV SLICER=prusaslicer
RUN pip install -r requirements.txt
RUN mkdir -p /root/.config/spoolman2slicer
RUN cp -r ./spoolman2slicer/data/* /root/.config/spoolman2slicer/
RUN mkdir /configs
ENTRYPOINT [ "sh", "-c", "python3 ./spoolman2slicer/spoolman2slicer.py -U -d /configs -s ${SLICER} -u ${SPOOLMAN_URL}" ]
