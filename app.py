import streamlit as st
import pandas as pd
import yfinance as yf
import smtplib
from email.mime.text import MIMEText
import plotly.graph_objects as go
import plotly.express as px
import numpy as np
import datetime
import time
import hashlib
from sklearn.ensemble import RandomForestClassifier
from streamlit_gsheets import GSheetsConnection


st.set_page_config(
    page_title="Borsa Pro Gold",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="collapsed"
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
    thead tr th:first-child {display:none} tbody th {display:none}
</style>
""", unsafe_allow_html=True)


conn = st.connection("gsheets", type=GSheetsConnection)

def sifrele(sifre):
    return hashlib.sha256(str.encode(sifre)).hexdigest()

def db_get_users():
    
    try:
        return conn.read(worksheet="users", ttl=0)
    except:
        return pd.DataFrame(columns=["username", "password"])

def db_add_user(username, password):
    df = db_get_users()
    if username in df['username'].values:
        return False 
    
    new_data = pd.DataFrame([{"username": username, "password": sifrele(password)}])
    updated_df = pd.concat([df, new_data], ignore_index=True)
    conn.update(worksheet="users", data=updated_df)
    return True

def db_get_takip(username):
    try:
        df = conn.read(worksheet="takip", ttl=0)
        user_list = df[df['username'] == username]['sembol'].tolist()
        if not user_list: return ["ASELS.IS"]
        return user_list
    except:
        return ["ASELS.IS"]

def db_add_takip(username, sembol):
    df = conn.read(worksheet="takip", ttl=0)
    
    if not df[(df['username'] == username) & (df['sembol'] == sembol)].empty:
        return
    
    new_row = pd.DataFrame([{"username": username, "sembol": sembol}])
    updated_df = pd.concat([df, new_row], ignore_index=True)
    conn.update(worksheet="takip", data=updated_df)

def db_del_takip(username, sembol):
    df = conn.read(worksheet="takip", ttl=0)
    
    updated_df = df[~((df['username'] == username) & (df['sembol'] == sembol))]
    conn.update(worksheet="takip", data=updated_df)

def db_get_portfoy(username):
    try:
        df = conn.read(worksheet="portfoy", ttl=0)
        return df[df['username'] == username]
    except:
        return pd.DataFrame()

def db_update_portfoy(username, sembol, adet, maliyet):
    df = conn.read(worksheet="portfoy", ttl=0)
    
    df = df[~((df['username'] == username) & (df['sembol'] == sembol))]
    
    
    new_row = pd.DataFrame([{"username": username, "sembol": sembol, "adet": float(adet), "maliyet": float(maliyet)}])
    updated_df = pd.concat([df, new_row], ignore_index=True)
    conn.update(worksheet="portfoy", data=updated_df)


def mail_gonder(kime, sembol, fiyat):
    try:
        if "gmail" in st.secrets:
            GONDEREN_MAIL = st.secrets["gmail"]["mail"]
            GONDEREN_SIFRE = st.secrets["gmail"]["sifre"]
        else: return False
        msg = MIMEText(f"{sembol} hedef fiyatiniza ulasti.\nGuncel: {fiyat}")
        msg['Subject'] = f"🚨 ALARM: {sembol}"
        msg['From'] = GONDEREN_MAIL
        msg['To'] = kime
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GONDEREN_MAIL, GONDEREN_SIFRE)
        server.sendmail(GONDEREN_MAIL, kime, msg.as_string())
        server.quit(); return True
    except: return False


@st.cache_data(ttl=60)
def veri_getir(sembol, periyot="1mo"):
    try:
        aralik = "1d"
        if periyot == "1d": aralik = "5m"
        elif periyot == "5d": aralik = "60m"
        
        
        if "ALTIN" in sembol or "GUMUS" in sembol:
            ticker = "GC=F" if "ALTIN" in sembol else "SI=F"
            ons = yf.Ticker(ticker).history(period=periyot, interval=aralik)
            dolar = yf.Ticker("USDTRY=X").history(period=periyot, interval=aralik)
            
            if ons.empty or dolar.empty: return pd.DataFrame()

            ons.index = ons.index.tz_localize(None)
            dolar.index = dolar.index.tz_localize(None)
            
            ons = ons[['Open', 'High', 'Low', 'Close']]
            dolar_close = dolar['Close']
            
            df = pd.concat([ons, dolar_close], axis=1)
            df.columns = ['Ons_Open', 'Ons_High', 'Ons_Low', 'Ons_Close', 'Dolar']
            df = df.ffill().bfill().dropna()

            for col in ['Open', 'High', 'Low', 'Close']:
                df[col] = (df[f'Ons_{col}'] * df['Dolar']) / 31.1035
            
            df = df[['Open', 'High', 'Low', 'Close']]
            df['Volume'] = 0
            df.reset_index(inplace=True)
            col = 'Date' if 'Date' in df.columns else 'Datetime'
            df = df.rename(columns={col: 'Date'})

        else:
            hisse = yf.Ticker(sembol)
            df = hisse.history(period=periyot, interval=aralik)
            df.reset_index(inplace=True)
            if 'Date' in df.columns: df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)
            elif 'Datetime' in df.columns: df['Date'] = pd.to_datetime(df['Datetime']).dt.tz_localize(None)
        
        return df
    except: return pd.DataFrame()

def teknik_analiz(df):
    if len(df) < 15: return df, "Veri Yetersiz"
    df['SMA_20'] = df['Close'].rolling(20).mean()
    std = df['Close'].rolling(20).std()
    df['Bollinger_Upper'] = df['SMA_20'] + (std * 2)
    df['Bollinger_Lower'] = df['SMA_20'] - (std * 2)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    sinyal = "NÖTR"
    if not pd.isna(df['RSI'].iloc[-1]):
        if df['RSI'].iloc[-1] < 30: sinyal = "AL 🟢"
        elif df['RSI'].iloc[-1] > 70: sinyal = "SAT 🔴"
    return df, sinyal

def gelismis_tahmin(df):
    try:
        df_temp = df.dropna(subset=['Close']).copy()
        if len(df_temp) < 10: return None
        df_temp['Date_Ordinal'] = df_temp['Date'].map(datetime.datetime.toordinal)
        x = df_temp['Date_Ordinal']; y = df_temp['Close']
        z = np.polyfit(x, y, 2); p = np.poly1d(z)
        tahmin_y = p(x); std_hata = np.std(y - tahmin_y)
        son_tarih = df_temp['Date'].iloc[-1]
        gelecek = [son_tarih + datetime.timedelta(days=i) for i in range(1, 8)]
        x_pred = [t.toordinal() for t in gelecek]
        y_pred = p(x_pred)
        return pd.DataFrame({'Date': gelecek, 'Tahmin': y_pred, 'Ust': y_pred + std_hata, 'Alt': y_pred - std_hata})
    except: return None

def mevsimsellik_analizi(df):
    try:
        df_temp = df.copy()
        df_temp['Gun'] = df_temp['Date'].dt.day_name()
        tr_gun = {'Monday':'Pazartesi', 'Tuesday':'Salı', 'Wednesday':'Çarşamba', 'Thursday':'Perşembe', 'Friday':'Cuma'}
        df_temp['Gun'] = df_temp['Gun'].map(tr_gun)
        df_temp['Getiri'] = df_temp['Close'].pct_change() * 100
        mevsim = df_temp.groupby('Gun')['Getiri'].mean()
        sirali = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma']
        mevsim = mevsim.reindex(sirali)
        return mevsim
    except: return pd.Series()

def ml_sinyal_uret(sembol):
    try:
        if "ALTIN" in sembol: ticker = "GC=F"
        elif "GUMUS" in sembol: ticker = "SI=F"
        else: ticker = sembol
        data = yf.Ticker(ticker).history(period="2y")
        if len(data) < 50: return "Veri Az", 0
        data['Getiri'] = data['Close'].pct_change()
        data['SMA_10'] = data['Close'].rolling(10).mean()
        data['SMA_50'] = data['Close'].rolling(50).mean()
        data['Target'] = np.where(data['Close'].shift(-1) > data['Close'], 1, 0)
        data = data.dropna()
        features = ['Open', 'High', 'Low', 'Close', 'SMA_10', 'SMA_50']
        if "Volume" in data.columns and data['Volume'].sum() > 0: features.append('Volume')
        X = data[features]; y = data['Target']
        model = RandomForestClassifier(n_estimators=100, min_samples_split=5, random_state=42)
        model.fit(X, y)
        prob = model.predict_proba(X.iloc[[-1]])[0][1]
        if prob >= 0.5: return "YUKSELIS 🚀", prob * 100
        else: return "DUSUS 🔻", (1 - prob) * 100
    except: return "Hesaplanamadı", 0


if 'login_status' not in st.session_state: st.session_state['login_status'] = False
if 'username' not in st.session_state: st.session_state['username'] = ''

def login_ekrani():
    st.markdown("<h1 style='text-align: center;'>💎 Borsa Pro Cloud</h1>", unsafe_allow_html=True)
    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        tab1, tab2 = st.tabs(["Giriş", "Kayıt"])
        with tab1:
            k = st.text_input("Kullanıcı Adı")
            s = st.text_input("Şifre", type="password")
            if st.button("Giriş Yap", use_container_width=True):
                
                users = db_get_users()
                hashed_pw = sifrele(s)
                
                
                if not users.empty and ((users['username'] == k) & (users['password'] == hashed_pw)).any():
                    st.session_state['login_status']=True
                    st.session_state['username']=k
                    st.rerun()
                else:
                    st.error("Hatalı!")
        with tab2:
            yk = st.text_input("Yeni K. Adı")
            ys = st.text_input("Yeni Şifre", type="password")
            if st.button("Kayıt Ol", use_container_width=True):
                if yk and ys:
                    with st.spinner("Google Sheets'e Kaydediliyor..."):
                        basarili = db_add_user(yk, ys)
                        if basarili:
                            db_add_takip(yk, "ASELS.IS") 
                            st.success("Başarılı! Giriş yapabilirsin.")
                        else:
                            st.warning("Bu kullanıcı adı alınmış.")


if not st.session_state['login_status']:
    login_ekrani()
else:
    user = st.session_state['username']
    
    st.sidebar.title(f"👤 {user}")
    if st.sidebar.button("Çıkış"): 
        st.session_state['login_status']=False
        st.rerun()
    st.sidebar.divider()
    
    
    l = db_get_takip(user)
    
    secilen = st.sidebar.selectbox("Hisse Seç", l)
    
    st.sidebar.subheader("Cüzdan (Sheets)")
    pdf = db_get_portfoy(user)
    
    if not pdf.empty:
        t_val=0; t_pl=0; html=""
        for i,r in pdf.iterrows():
            v=veri_getir(r['sembol'],"1d")
            cur = v.iloc[-1]['Close'] if not v.empty else r['maliyet']
            val=cur*r['adet']; pl=val-(r['maliyet']*r['adet']); t_val+=val; t_pl+=pl
            c="#0ecb81" if pl>=0 else "#f6465d"
            html+=f"<div class='midas-card' style='border-left:4px solid {c}'><div style='display:flex;justify-content:space-between'><b>{r['sembol'].replace('.IS','')}</b><span style='color:{c}'>{cur:.2f}</span></div><div style='font-size:0.8em;color:#888'>{int(r['adet'])} Adet • Kar: {pl:.0f}</div></div>"
        st.sidebar.markdown(f"<div style='text-align:center;padding:15px;background:#222;border-radius:10px;margin-bottom:10px'><b>TOPLAM</b><br><span style='font-size:1.5em'>{t_val:,.0f} TL</span><br><span style='color:{'#0ecb81' if t_pl>=0 else '#f6465d'}'>{t_pl:,.0f} TL</span></div>", unsafe_allow_html=True)
        st.sidebar.markdown(html, unsafe_allow_html=True)

    with st.sidebar.expander("Ekle/Sil"):
        kod=st.text_input("Kod").upper()
        c1,c2=st.columns(2)
        if c1.button("Ekle"):
            if "ALTIN" not in kod and "GUMUS" not in kod and ".IS" not in kod: kod+=".IS"
            with st.spinner("Google Sheets Güncelleniyor..."):
                db_add_takip(user, kod)
            st.rerun()
        if c2.button("Sil"):
            with st.spinner("Siliniyor..."):
                db_del_takip(user, secilen)
            st.rerun()

    
    st.title(f"{secilen.replace('.IS','')} Analiz")
    
    c1,c2 = st.columns([1,3])
    gr_tip = c1.radio("Tip", ["Mum","Cizgi"])
    zaman = c2.radio("Zaman", ["1G","1H","1A","1Y"], horizontal=True, index=2)
    p_map = {"1G":"1d","1H":"5d","1A":"1mo","1Y":"1y"}
    
    df = veri_getir(secilen, p_map[zaman])
    
    if not df.empty and len(df)>1:
        df, sinyal = teknik_analiz(df)
        ai_df = gelismis_tahmin(df) 
        ml_y, ml_g = ml_sinyal_uret(secilen)
        son = df.iloc[-1]['Close']; fark = son - df.iloc[0]['Close']; yuzde = (fark/df.iloc[0]['Close'])*100
        
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Fiyat", f"{son:.2f}", f"%{yuzde:.2f}")
        
        m2.metric("AI Sinyal", ml_y, f"%{ml_g:.0f} Güven", help="Random Forest (Makine Öğrenmesi) modeli geçmiş 2 yıllık veriyi tarar. %50'den yüksekse sinyal üretir.")
        m3.metric("RSI", f"{df['RSI'].iloc[-1]:.0f}", sinyal, help="RSI:\n30'un altı: Hisse çok ucuz (Al Fırsatı)\n70'in üstü: Hisse çok pahalı (Satış Riski)")
        if ai_df is not None and 'Tahmin' in ai_df.columns:
            tyon = "Yükseliş" if ai_df['Tahmin'].iloc[-1] > son else "Düşüş"
            m4.metric("Trend", tyon, help="Polinom Regresyon: Fiyatın matematiksel ana yönünü (Sarı Çizgi) gösterir.")
        else: m4.metric("Trend", "--")

        fig = go.Figure()
        renk = '#00ff00' if fark>=0 else '#ff0000'
        
        if gr_tip=="Mum": fig.add_trace(go.Candlestick(x=df['Date'], open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Fiyat'))
        else: fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], mode='lines', line=dict(color=renk, width=4), name='Fiyat'))
        
        if 'Bollinger_Upper' in df:
            fig.add_trace(go.Scatter(x=df['Date'], y=df['Bollinger_Upper'], line=dict(color='gray', width=1), name='Üst Bant'))
            fig.add_trace(go.Scatter(x=df['Date'], y=df['Bollinger_Lower'], fill='tonexty', fillcolor='rgba(255, 255, 255, 0.05)', line=dict(color='gray', width=1), name='Alt Bant'))
        
        if ai_df is not None:
             fig.add_trace(go.Scatter(x=ai_df['Date'], y=ai_df['Tahmin'], line=dict(color='yellow', dash='dot', width=2), name='AI Trend'))
             fig.add_trace(go.Scatter(x=ai_df['Date'], y=ai_df['Alt'], fill='tonexty', fillcolor='rgba(255, 255, 0, 0.15)', line=dict(width=0), name='Güven Aralığı'))
        
        
        min_y = df['Low'].min() * 0.999
        max_y = df['High'].max() * 1.001
        
        fig.update_layout(height=450, template="plotly_dark", margin=dict(t=30,b=0), yaxis=dict(range=[min_y, max_y]))
        st.plotly_chart(fig, use_container_width=True)
        
        with st.expander("ℹ️ Grafikteki Çizgiler"):
            st.write("Sarı: Trend Rotası, Gri: Bollinger Bantları (Pahalı/Ucuz Sınırı)")

        with st.expander("💰 İşlem Yap (Cloud)"):
            ad = st.number_input("Adet", 1.0); mal = st.number_input("Maliyet", son)
            if st.button("Kaydet"):
                with st.spinner("Google Sheets'e Yazılıyor..."):
                    db_update_portfoy(user, secilen, ad, mal)
                st.success("Buluta Kaydedildi! ☁️")
                time.sleep(1)
                st.rerun()

        
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🧬 AI & Mevsimsellik", "📊 Risk", "📋 Veri", "🔔 Alarm", "🆚 Kıyasla"])

        with tab1: 
            c1,c2=st.columns(2)
            with c1:
                st.subheader("Mevsimsellik Analizi")
                st.info("📊 **Bu Grafik Nedir?**\nGeçmişe bakarak, hissenin haftanın hangi günlerinde kazandırdığını gösterir.")
                md = mevsimsellik_analizi(df)
                if not md.empty: st.plotly_chart(px.bar(x=md.index, y=md.values, color=md.values, color_continuous_scale='RdYlGn', labels={'x':'Gün','y':'Getiri %'}), use_container_width=True)
            with c2:
                st.subheader("AI Detay")
                st.info(f"🤖 **Random Forest Nedir?**\nGeçmiş veriyi tarayan yapay zeka modelidir.\n\n**Analiz Sonucu:**\nModel %{ml_g:.0f} ihtimalle **{ml_y}** bekliyor.")

        with tab2: 
            st.subheader("Risk Dağılımı")
            st.info("📉 **Histogram Nedir?**\nGrafik sağa-sola çok yayılmışsa hisse **çok oynak (Riskli)** demektir. Ortada toplanmışsa sakindir.")
            ret = df['Close'].pct_change().dropna()*100
            st.plotly_chart(go.Figure(data=[go.Histogram(x=ret, nbinsx=40, marker_color='#3b8ed0')]).update_layout(height=300, template="plotly_dark"), use_container_width=True)

        with tab3: 
            st.subheader("Geçmiş Veriler (Türkçe)")
            tablo = df.copy()
            tablo = tablo.rename(columns={'Date': 'Tarih', 'Open': 'Açılış', 'High': 'Yüksek', 'Low': 'Düşük', 'Close': 'Kapanış', 'RSI': 'RSI Gücü'})
            st.dataframe(tablo[['Tarih', 'Açılış', 'Yüksek', 'Düşük', 'Kapanış', 'RSI Gücü']].sort_values('Tarih', ascending=False), use_container_width=True, hide_index=True)

        with tab4: 
            hf = st.number_input("Hedef Fiyat", son*0.95); mail = st.text_input("Mail")
            if st.button("Kur"):
                if son <= hf: mail_gonder(mail, secilen, son); st.success("Mail atıldı!")
                else: st.warning("Düşmedi.")
        
        with tab5:
            st.subheader(f"{secilen} Kıyasla")
            st.info("Listenizdeki hisseler ve standart varlıklar (Dolar, BIST100) arasından seçim yapın.")
            
            standartlar = ["USDTRY=X", "EURTRY=X", "XU100.IS", "GC=F"]
            kiy_listesi = standartlar + [x for x in l if x != secilen]
            
            karsit = st.selectbox("Kıyaslanacak Varlık Seç", kiy_listesi)
            
            if karsit:
                df2 = veri_getir(karsit, p_map[zaman])
                if not df2.empty:
                    df_comp = pd.merge(df[['Date','Close']], df2[['Date','Close']], on='Date', suffixes=('_1', '_2')).dropna()
                    if not df_comp.empty:
                        df_comp['Norm_1'] = ((df_comp['Close_1'] / df_comp['Close_1'].iloc[0]) - 1) * 100
                        df_comp['Norm_2'] = ((df_comp['Close_2'] / df_comp['Close_2'].iloc[0]) - 1) * 100
                        
                        corr = df_comp['Close_1'].corr(df_comp['Close_2'])
                        st.metric("Korelasyon (Benzerlik)", f"{corr:.2f}", help="1'e yakınsa birlikte hareket ediyorlar.")
                        
                        fig_c = go.Figure()
                        fig_c.add_trace(go.Scatter(x=df_comp['Date'], y=df_comp['Norm_1'], mode='lines', name=secilen, line=dict(color='#00ff00', width=2)))
                        fig_c.add_trace(go.Scatter(x=df_comp['Date'], y=df_comp['Norm_2'], mode='lines', name=karsit, line=dict(color='#0000ff', width=2)))
                        fig_c.update_layout(height=400, template="plotly_dark", title="Getiri Farkı (%)")
                        st.plotly_chart(fig_c, use_container_width=True)
                    else: st.warning("Tarih çakışması yok.")
                else: st.error("Veri yok.")

    else: st.error("Veri alınamadı.")

