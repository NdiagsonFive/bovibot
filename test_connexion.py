import pymysql

try:
    conn = pymysql.connect(
        host='interchange.proxy.rlwy.net',
        port=19432,
        user='root',
        password='FieiQZXqdMZSefpfoVekxrNPsRAvOWUW',
        database='railway'
    )
    print('✅ CONNECTE !')
    conn.close()
except Exception as e:
    print(f'❌ ERREUR : {e}')