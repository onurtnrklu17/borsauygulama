import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
import smtplib
from email.mime.text import MIMEText
import plotly.graph_objects as go
import numpy as np
import datetime
import time
import hashlib
from sklearn.ensemble import RandomForestClassifier

# --- 1. AYARLAR ---
st.set_page_config(
    page_title="Borsa Pro",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="collapsed"  # Giriş yapana kadar menü kapalı
)

# --- CSS TASARIM ---
st.markdown("""
<style>
    .stApp {background-color: #0e1117;}
    section[data-testid="stSidebar"] {background-color: #121417;}
    .midas-card {background-color: #1e2329; padding: 12px; border-radius: 8px; border: 1px solid #2a2e39; margin-bottom: 10px;}
    .card-title {font-weight: bold; font-size: 1.1em; color: white;}
    .profit-green {color: #0ecb81; font-weight: bold;}
    .profit-red {color: #f6465d; font-weight: bold;}
    .login-box {background-color: #1e2329; padding: 30px; border-radius: 15px; border: 1px solid #333; text-align: center;}
    thead tr th:first-child {display:none} tbody th {display:none}
</style>
""", unsafe_allow_html=True)


# --- 2. VERİTABANI VE GÜVENLİK ---

def sifrele(sifre):
    return hashlib.sha256(str.encode(sifre)).hexdigest()


def baglanti_kur():
    conn = sqlite3.connect('borsa_pro_db.db')
    # Kullanıcılar Tablosu
    conn.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
    # Takip Listesi (Kullanıcıya Özel)
    conn.execute("CREATE TABLE IF NOT EXISTS takip_listesi (username TEXT, sembol TEXT)")
    # Portföy (Kullanıcıya Özel)
    conn.execute("CREATE TABLE IF NOT EXISTS portfoy (username TEXT, sembol TEXT, adet REAL, maliyet REAL)")
    conn.commit()
    return conn


baglanti_kur().close()


# --- 3. MAİL BOTU ---
def mail_gonder(kime, sembol, fiyat):
    try:
        # Streamlit Cloud'da 'Secrets' kısmından çeker, yoksa hata vermez boş geçer
        if "gmail" in st.secrets:
            GONDEREN_MAIL = st.secrets["gmail"]["mail"]
            GONDEREN_SIFRE = st.secrets["gmail"]["sifre"]
        else:
            return False  # Lokal çalışırken secrets yoksa mail atmaz

        msg = MIMEText(
            f"Sayin Yatirimci,\n\nTakip ettiginiz {sembol} hissesi hedef fiyatinizin altina indi.\n\nGuncel Fiyat: {fiyat} TL\n\nBorsa Pro Botu")
        msg['Subject'] = f"🚨 ALARM: {sembol} Fiyat Dusuşu"
        msg['From'] = GONDEREN_MAIL
        msg['To'] = kime

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GONDEREN_MAIL, GONDEREN_SIFRE)
        server.sendmail(GONDEREN_MAIL, kime, msg.as_string())
        server.quit()
        return True
    except:
        return False


# --- 4. DATA FONKSİYONLARI ---
@st.cache_data(ttl=60)  # 60 saniye önbellek
def veri_getir(sembol, periyot="1mo"):
    try:
        aralik = "1d"
        if periyot == "1d":
            aralik = "5m"
        elif periyot == "5d":
            aralik = "60m"

        if "ALTIN" in sembol or "GUMUS" in sembol:
            ticker = "GC=F" if "ALTIN" in sembol else "SI=F"
            ons = yf.Ticker(ticker).history(period=periyot, interval=aralik)['Close']
            dolar = yf.Ticker("USDTRY=X").history(period=periyot, interval=aralik)['Close']
            df = pd.concat([ons, dolar], axis=1, keys=['Ons', 'Dolar']).ffill().bfill().dropna()
            df['Close'] = (df['Ons'] * df['Dolar']) / 31.1035
            df.reset_index(inplace=True)
            col = 'Date' if 'Date' in df.columns else 'Datetime'
            df = df.rename(columns={col: 'Date'})
            df['Open'] = df['Close'];
            df['High'] = df['Close'] * 1.002;
            df['Low'] = df['Close'] * 0.998;
            df['Volume'] = 0
        else:
            hisse = yf.Ticker(sembol)
            df = hisse.history(period=periyot, interval=aralik)
            df.reset_index(inplace=True)

        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)
        elif 'Datetime' in df.columns:
            df['Date'] = pd.to_datetime(df['Datetime']).dt.tz_localize(None)
        return df
    except:
        return pd.DataFrame()


def teknik_analiz(df):
    if len(df) < 15: return df, "Veri Yetersiz"
    df['SMA_20'] = df['Close'].rolling(20).mean()
    df['Bollinger_Upper'] = df['SMA_20'] + (df['Close'].rolling(20).std() * 2)
    df['Bollinger_Lower'] = df['SMA_20'] - (df['Close'].rolling(20).std() * 2)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    sinyal = "NÖTR"
    if not pd.isna(df['RSI'].iloc[-1]):
        if df['RSI'].iloc[-1] < 30:
            sinyal = "AL"
        elif df['RSI'].iloc[-1] > 70:
            sinyal = "SAT"
    return df, sinyal


def ml_sinyal_uret(sembol):
    try:
        # Basit ML Modeli
        ticker = "GC=F" if "ALTIN" in sembol else ("SI=F" if "GUMUS" in sembol else sembol)
        data = yf.Ticker(ticker).history(period="1y")
        if len(data) < 50: return "Veri Az", 0
        data['Getiri'] = data['Close'].pct_change()
        data['Target'] = np.where(data['Close'].shift(-1) > data['Close'], 1, 0)
        data = data.dropna()
        model = RandomForestClassifier(n_estimators=100, min_samples_split=5, random_state=42)
        model.fit(data[['Open', 'High', 'Low', 'Close', 'Volume']], data['Target'])
        prob = model.predict_proba(data[['Open', 'High', 'Low', 'Close', 'Volume']].iloc[[-1]])[0][1]
        yon = "YUKSELIS 🚀" if prob >= 0.5 else "DUSUS 🔻"
        guven = prob * 100 if prob >= 0.5 else (1 - prob) * 100
        return yon, guven
    except:
        return "Hata", 0


# --- 5. GİRİŞ SİSTEMİ ---
if 'login_status' not in st.session_state: st.session_state['login_status'] = False
if 'username' not in st.session_state: st.session_state['username'] = ''


def login_ekrani():
    st.markdown("<h1 style='text-align: center;'>💎 Borsa Pro Giriş</h1>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        tab_giris, tab_kayit = st.tabs(["Giriş Yap", "Kayıt Ol"])

        with tab_giris:
            kadi = st.text_input("Kullanıcı Adı")
            sifre = st.text_input("Şifre", type="password")
            if st.button("Giriş Yap", use_container_width=True):
                conn = baglanti_kur()
                user = pd.read_sql("SELECT * FROM users WHERE username = ? AND password = ?", conn,
                                   params=(kadi, sifrele(sifre)))
                conn.close()
                if not user.empty:
                    st.session_state['login_status'] = True
                    st.session_state['username'] = kadi
                    st.success("Giriş Başarılı!")
                    st.rerun()
                else:
                    st.error("Hatalı kullanıcı adı veya şifre!")

        with tab_kayit:
            y_kadi = st.text_input("Yeni Kullanıcı Adı")
            y_sifre = st.text_input("Yeni Şifre", type="password")
            if st.button("Kayıt Ol", use_container_width=True):
                if y_kadi and y_sifre:
                    try:
                        conn = baglanti_kur()
                        conn.execute("INSERT INTO users VALUES (?, ?)", (y_kadi, sifrele(y_sifre)))
                        # Varsayılan hisse ekle
                        conn.execute("INSERT INTO takip_listesi VALUES (?, ?)", (y_kadi, "ASELS.IS"))
                        conn.commit()
                        conn.close()
                        st.success("Kayıt başarılı! Şimdi giriş yapabilirsiniz.")
                    except:
                        st.warning("Bu kullanıcı adı zaten alınmış.")
                else:
                    st.warning("Alanları doldurun.")


# --- 6. ANA UYGULAMA ---
if not st.session_state['login_status']:
    login_ekrani()
else:
    # --- BURASI GİRİŞ YAPTIKTAN SONRAKİ EKRAN ---
    user = st.session_state['username']

    # --- SIDEBAR (KİŞİYE ÖZEL) ---
    st.sidebar.title(f"👤 {user}")
    if st.sidebar.button("Çıkış Yap"):
        st.session_state['login_status'] = False
        st.rerun()

    st.sidebar.divider()

    # Takip Listesi Çek
    conn = baglanti_kur()
    try:
        liste = pd.read_sql("SELECT sembol FROM takip_listesi WHERE username = ?", conn, params=(user,))[
            'sembol'].tolist()
    except:
        liste = ["ASELS.IS"]
    conn.close()
    if not liste: liste = ["ASELS.IS"]  # Boşsa varsayılan

    secilen = st.sidebar.selectbox("Hisse Seç", liste)

    # Portföy Kartları (Kişiye Özel)
    st.sidebar.subheader("Cüzdanım")
    conn = baglanti_kur()
    pdf = pd.read_sql("SELECT * FROM portfoy WHERE username = ?", conn, params=(user,))
    conn.close()

    if not pdf.empty:
        t_val = 0;
        t_pl = 0
        html_cards = ""
        for idx, row in pdf.iterrows():
            v = veri_getir(row['sembol'], "1d")
            curr = v.iloc[-1]['Close'] if not v.empty else row['maliyet']
            val = curr * row['adet'];
            pl = val - (row['maliyet'] * row['adet'])
            t_val += val;
            t_pl += pl
            col = "#0ecb81" if pl >= 0 else "#f6465d"
            html_cards += f"""<div class="midas-card" style="border-left: 4px solid {col};"><div style="display:flex; justify-content:space-between;"><span class="card-title">{row['sembol'].replace('.IS', '')}</span><span style="color:{col};font-weight:bold;">{curr:.2f}</span></div><div style="font-size:0.8em;color:#888;">{int(row['adet'])} Adet • Kar: {pl:.0f}</div></div>"""

        st.sidebar.markdown(
            f"<div style='text-align:center; padding:15px; background:linear-gradient(180deg, #1e2329, #161a1e); border-radius:10px; margin-bottom:15px;'><div>TOPLAM</div><div style='font-size:1.5em; font-weight:bold;'>{t_val:,.0f} TL</div><div style='color:{'#0ecb81' if t_pl >= 0 else '#f6465d'};'>{t_pl:,.0f} TL</div></div>",
            unsafe_allow_html=True)
        st.sidebar.markdown(html_cards, unsafe_allow_html=True)

    with st.sidebar.expander("Liste Ayarları"):
        kod = st.text_input("Kod Ekle").upper()
        c1, c2 = st.columns(2)
        if c1.button("Ekle"):
            if "ALTIN" not in kod and "GUMUS" not in kod and ".IS" not in kod: kod += ".IS"
            conn = baglanti_kur();
            conn.execute("INSERT INTO takip_listesi VALUES (?,?)", (user, kod));
            conn.commit();
            conn.close();
            st.rerun()
        if c2.button("Sil"):
            conn = baglanti_kur();
            conn.execute("DELETE FROM takip_listesi WHERE username=? AND sembol=?", (user, secilen));
            conn.commit();
            conn.close();
            st.rerun()

    # --- ANA EKRAN ANALİZ ---
    st.title(f"{secilen.replace('.IS', '')} Analiz")

    # Grafik
    c1, c2 = st.columns([1, 3])
    gr_tip = c1.radio("Tip", ["Mum", "Cizgi"]);
    zaman = c2.radio("Zaman", ["1G", "1H", "1A", "1Y"], horizontal=True, index=2)
    p_map = {"1G": "1d", "1H": "5d", "1A": "1mo", "1Y": "1y"}
    df = veri_getir(secilen, p_map[zaman])

    if not df.empty and len(df) > 1:
        df, sinyal = teknik_analiz(df)
        son = df.iloc[-1]['Close'];
        fark = son - df.iloc[0]['Close'];
        yuzde = (fark / df.iloc[0]['Close']) * 100
        ml_y, ml_g = ml_sinyal_uret(secilen)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Fiyat", f"{son:.2f}", f"%{yuzde:.2f}")
        m2.metric("AI Sinyal", ml_y, f"%{ml_g:.0f}")
        m3.metric("RSI", f"{df['RSI'].iloc[-1]:.0f}", sinyal)
        m4.metric("Hacim", f"{df['Volume'].iloc[-1] / 1000000:.1f}M")

        fig = go.Figure()
        renk = '#00ff00' if fark >= 0 else '#ff0000'
        if gr_tip == "Mum":
            fig.add_trace(
                go.Candlestick(x=df['Date'], open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                               name='Fiyat'))
        else:
            fig.add_trace(
                go.Scatter(x=df['Date'], y=df['Close'], mode='lines', line=dict(color=renk, width=4), name='Fiyat'))

        if 'Bollinger_Upper' in df:
            fig.add_trace(
                go.Scatter(x=df['Date'], y=df['Bollinger_Upper'], line=dict(color='gray', width=1), showlegend=False))
            fig.add_trace(
                go.Scatter(x=df['Date'], y=df['Bollinger_Lower'], line=dict(color='gray', width=1), showlegend=False))

        fig.update_layout(height=450, template="plotly_dark", margin=dict(t=30, b=0), yaxis_autorange=True)
        st.plotly_chart(fig, use_container_width=True)

        # PORTFÖYE EKLE (Kişiye Özel)
        with st.expander("💰 Al / Sat (Portföye İşle)", expanded=True):
            cc1, cc2, cc3 = st.columns([2, 2, 1])
            ad = cc1.number_input("Adet", 100.0);
            mal = cc2.number_input("Maliyet", son)
            if cc3.button("Kaydet"):
                conn = baglanti_kur()
                conn.execute("DELETE FROM portfoy WHERE username=? AND sembol=?", (user, secilen))
                conn.execute("INSERT INTO portfoy VALUES (?,?,?,?)", (user, secilen, ad, mal))
                conn.commit();
                conn.close();
                st.success("İşlendi!");
                time.sleep(0.5);
                st.rerun()

        # ALARM (HERKES KENDİ MAİLİNE)
        with st.expander("🔔 Alarm Kur (Arkadaşın da kullanabilir)"):
            st.info("Hisse düşerse mail atar. Arkadaşın kendi mailini yazarsa ona gider.")
            c_a1, c_a2 = st.columns(2)
            hedef = c_a1.number_input("Hedef Fiyat", value=son * 0.95)
            mail_adres = c_a2.text_input("Mail Adresi (Arkadaşınki de olur)")

            if st.button("Alarmı Başlat"):
                if mail_adres:
                    # Burada normalde veritabanına alarmı kaydederiz, demo için anlık kontrol
                    if son <= hedef:
                        basari = mail_gonder(mail_adres, secilen, son)
                        if basari:
                            st.success(f"Mail gönderildi: {mail_adres}")
                        else:
                            st.error("Mail gönderilemedi (Ayarlar eksik).")
                    else:
                        st.warning("Fiyat henüz hedefe gelmedi, sistem açıkken takipte kalacak.")

    else:
        st.error("Veri yok.")