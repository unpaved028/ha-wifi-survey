# HA-App „WiFi Survey“. Gebaut wird aus diesem Ordner mit dem Python-Paket als Wheel (wheels/), festen Abhängigkeiten
# (requirements.txt) und der Android-App (apk/): als lokale App mit scripts/ha_app_build.sh (der Supervisor baut auf dem
# HA-Rechner), öffentlich mit GitHub Actions (.github/workflows/build.yaml im Repository ha-wifi-survey).
# Basis ist das offizielle Python-Abbild (Debian) statt des Alpine-Abbilds von HA: NumPy und
# OpenCV gibt es dort als fertige Wheels für aarch64 und amd64, unter Alpine müssten sie kompiliert werden.
FROM python:3.13-slim-trixie

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r /tmp/requirements.txt
COPY wheels/ /tmp/wheels/
RUN pip install --no-cache-dir --root-user-action=ignore --no-deps /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels /tmp/requirements.txt

COPY apk/ /opt/wifi-survey/

ENV WIFI_SURVEY_DATA=/data \
    WIFI_SURVEY_APK=/opt/wifi-survey/wifi-survey.apk \
    PYTHONUNBUFFERED=1

EXPOSE 8099
CMD ["wifi-survey", "serve", "--host", "0.0.0.0", "--port", "8099", "--no-access-log"]
