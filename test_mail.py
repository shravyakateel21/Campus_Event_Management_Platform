import smtplib, ssl

user = "shravyakateel2004@gmail.com"
pw = input("Paste app password: ").replace(" ", "").strip()
TO = "shravyakateel21@gmail.com"

print("length:", len(pw), "(must be 16)")
try:
    s = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
    s.starttls(context=ssl.create_default_context())
    s.login(user, pw)
    s.sendmail(user, TO, "Subject: Test\n\nIt works.")
    s.quit()
    print("SENT OK")
except smtplib.SMTPAuthenticationError as e:
    print("GOOGLE REJECTED THE LOGIN:", e.smtp_code)
except Exception as e:
    print("FAILED:", type(e).__name__, e)