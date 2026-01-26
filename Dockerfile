# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

FROM python:3.10-slim

COPY [".", "."]
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV SLICER=prusaslicer
ENV SPOOLMAN_URL=https://spoolman.local:7912/
RUN pip install --upgrade pip
RUN pip install .
RUN mkdir -p /root/.config/spoolman2slicer
RUN cp -r ./spoolman2slicer/data/* /root/.config/spoolman2slicer/
RUN mkdir -p /configs
ENTRYPOINT [ "sh", "-c", "spoolman2slicer -U -d /configs -s ${SLICER} -u ${SPOOLMAN_URL}" ]
