# NoxPhisher
**Reconocimiento pasivo de visitantes** — IPv4 + IPv6 + QR + Deduplicación + SQLite  
by [@nostraxiten](https://github.com/nostraxiten)

> El autor no se responsabiliza del uso indebido de esta herramienta.

---

## ¿Qué hace?

Al acceder al enlace generado, el visitante ve una pantalla de carga y es redirigido a Google. En ese intervalo la herramienta captura en segundo plano:

- IP pública real vía `CF-Connecting-IP`
- IP privada local IPv4 e IPv6 vía WebRTC leak
- Geolocalización: país, región, ciudad, coordenadas, ISP, ASN
- Fingerprint del dispositivo: navegador, SO, pantalla, RAM, núcleos de CPU
- Fecha y hora exacta de cada captura

Todo queda guardado automáticamente en `captures.db` (SQLite).

---

## Requisitos

- Python 3.8+
- [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) instalado y en el PATH
- Termux (Android) o cualquier sistema Linux

---

## Instalación

```bash
# Clonar el repositorio
git clone https://github.com/nostraxiten/NoxPhisher
cd NoxPhisher

# Instalar dependencias
pip install -r requirements.txt --break-system-packages
```

---

## Uso

```bash
python noxphisher.py -h
```

### Opciones

| Flag | Descripción | Por defecto |
|------|-------------|-------------|
| `--qr` | Genera un QR del enlace en la terminal | Desactivado |
| `--window N` | Ventana de deduplicación en segundos | `60` |
| `--port N` | Puerto del servidor local | `8080` |
| `--view [N]` | Ver las últimas N capturas sin levantar el servidor | `50` |

### Ejemplos

```bash
# Ejecución básica
python noxphisher.py

# Con QR generado en terminal
python noxphisher.py --qr

# Puerto y ventana de deduplicación personalizados
python noxphisher.py --port 9090 --window 300

# Ver las últimas 20 capturas
python noxphisher.py --view 20
```

---

## Estructura

```
NoxPhisher/
├── noxphisher.py       # Script principal
├── requirements.txt    # Dependencias Python
├── captures.db         # Base de datos SQLite (se genera al ejecutar)
└── grabber_web/
    └── index.html      # Página servida al visitante
```

---

## Output de captura

```
======================================================================
[!] CAPTURA #1 [2026-01-01 12:00:00]
======================================================================
  IP Pública:   198.51.100.42 (IPv4)
  IP Privada:   192.168.1.105
  País:         Germany
  Región:       Bavaria
  Ciudad:       Munich
  ISP:          Deutsche Telekom AG
  Organización: Telekom Deutschland GmbH
  AS:           AS3320 Deutsche Telekom AG
  Coordenadas:  48.1351, 11.5820
  Google Maps:  https://www.google.com/maps?q=48.1351,11.5820
  Navegador:    Firefox
  Idioma:       de-DE
  Pantalla:     1920x1080
  Plataforma:   Win32
  RAM:          16GB
  Núcleos:      8
======================================================================
```

---

## Notas técnicas

- El tunnel se genera automáticamente con `cloudflared` — sin cuenta ni autenticación
- La deduplicación combina IP pública + fingerprint para evitar duplicados por recarga
- La notificación en Termux requiere `termux-api` instalado
- `cloudflared` no va en `requirements.txt` — se instala como binario aparte

---

## Dependencias

```
requests
qrcode
pillow
```

---

*NoxPhisher — parte de la suite de [@nostraxiten](https://github.com/nostraxiten)*

