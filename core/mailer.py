import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import dotenv

dotenv.load_dotenv("./.env")

SMTP_HOST = os.environ.get("SMTP_HOST")   # change to your provider's SMTP host
SMTP_PORT = int(os.environ.get("SMTP_PORT"))
SMTP_USER = os.environ.get("SMTP_USER")   # your sending address e.g. noreply@solfer.app
SMTP_KEY  = os.environ.get("SMTP_KEY")
SMTP_CUST_SERVICE_MAIL = os.environ.get("SMTP_CUST_SERVICE_MAIL")


def send_reset_email(to_address: str, reset_url: str) -> None:
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>Reset your Solfer password</title>
    </head>
    <body style="margin:0;padding:0;background:#f5f4f1;font-family:'Inter',system-ui,sans-serif;">

      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f4f1;padding:40px 16px;">
        <tr><td align="center">

          <table width="100%" cellpadding="0" cellspacing="0"
                 style="max-width:480px;background:#ffffff;border:1px solid #e0ddd6;
                        border-radius:16px;overflow:hidden;">

            <!-- Header -->
            <tr>
              <td style="background:#ffffff;padding:28px 36px 20px;
                         border-bottom:1px solid #e0ddd6;">
                <span style="font-size:20px;font-weight:600;letter-spacing:-0.5px;
                              color:#1a1a18;">
                  Sol<span style="color:#185FA5;">fer</span>
                </span>
              </td>
            </tr>

            <!-- Decorative solfa strip -->
            <tr>
              <td style="background:#f0efe9;padding:10px 36px;
                         font-family:Georgia,serif;font-size:14px;
                         color:#9a9a94;letter-spacing:0.5px;
                         border-bottom:1px solid #e0ddd6;">
                4&#8260;4&nbsp;&nbsp;d&nbsp;:&nbsp;
                <span style="color:#185FA5;font-style:italic;">m</span>&nbsp;:&nbsp;
                s&nbsp;:&nbsp;d'&nbsp;&nbsp;|&nbsp;&nbsp;
                <span style="color:#185FA5;font-style:italic;">l</span>&nbsp;:&nbsp;
                t&nbsp;:&nbsp;d'&nbsp;:&nbsp;–
              </td>
            </tr>

            <!-- Body -->
            <tr>
              <td style="padding:36px 36px 28px;">
                <p style="margin:0 0 8px;font-size:20px;font-weight:600;
                           color:#1a1a18;letter-spacing:-0.3px;">
                  Reset your password
                </p>
                <p style="margin:0 0 28px;font-size:14px;color:#5a5a56;line-height:1.65;">
                  We received a request to reset the password for your Solfer account.
                  Click the button below to choose a new one.
                  This link expires in <strong style="color:#1a1a18;">1 hour</strong>.
                </p>

                <!-- CTA button -->
                <table cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
                  <tr>
                    <td style="background:#185FA5;border-radius:8px;">
                      <a href="{reset_url}"
                         style="display:inline-block;padding:12px 28px;
                                font-size:14px;font-weight:500;color:#ffffff;
                                text-decoration:none;letter-spacing:-0.1px;">
                        Set new password →
                      </a>
                    </td>
                  </tr>
                </table>

                <!-- Fallback URL -->
                <p style="margin:0 0 6px;font-size:12px;color:#9a9a94;">
                  Button not working? Copy and paste this link into your browser:
                </p>
                <p style="margin:0;font-size:11px;color:#185FA5;word-break:break-all;">
                  {reset_url}
                </p>
              </td>
            </tr>

            <!-- Footer -->
            <tr>
              <td style="padding:18px 36px;border-top:1px solid #e0ddd6;
                         background:#f0efe9;">
                <p style="margin:0;font-size:11px;color:#9a9a94;line-height:1.6;">
                  If you didn't request a password reset you can safely ignore this email —
                  your password will not change.<br><br>
                  &copy; 2025 Solfer
                </p>
              </td>
            </tr>

          </table>
        </td></tr>
      </table>

    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset your Solfer password"
    msg["From"]    = f"Solfer <{SMTP_CUST_SERVICE_MAIL}>"
    msg["To"]      = to_address
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_KEY)
        server.sendmail(SMTP_USER, to_address, msg.as_string())

def send_receipt_email(email_dest: str, cust_name: str, amount: str, reason: str) -> None:
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>Solfer Payment Receipt</title>
    </head>
    <body style="margin:0;padding:0;background:#f5f4f1;font-family:'Inter',system-ui,sans-serif;">

      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f4f1;padding:40px 16px;">
        <tr><td align="center">

          <table width="100%" cellpadding="0" cellspacing="0"
                 style="max-width:480px;background:#ffffff;border:1px solid #e0ddd6;
                        border-radius:16px;overflow:hidden;">

            <!-- Header -->
            <tr>
              <td style="background:#ffffff;padding:28px 36px 20px;
                         border-bottom:1px solid #e0ddd6;">
                <span style="font-size:20px;font-weight:600;letter-spacing:-0.5px;
                              color:#1a1a18;">
                  Sol<span style="color:#185FA5;">fer</span>
                </span>
              </td>
            </tr>

            <!-- Decorative solfa strip -->
            <tr>
              <td style="background:#f0efe9;padding:10px 36px;
                         font-family:Georgia,serif;font-size:14px;
                         color:#9a9a94;letter-spacing:0.5px;
                         border-bottom:1px solid #e0ddd6;">
                4&#8260;4&nbsp;&nbsp;d&nbsp;:&nbsp;
                <span style="color:#185FA5;font-style:italic;">m</span>&nbsp;:&nbsp;
                s&nbsp;:&nbsp;d'&nbsp;&nbsp;|&nbsp;&nbsp;
                <span style="color:#185FA5;font-style:italic;">l</span>&nbsp;:&nbsp;
                t&nbsp;:&nbsp;d'&nbsp;:&nbsp;–
              </td>
            </tr>

            <!-- Body -->
            <tr>
              <td style="padding:36px 36px 28px;">

                <p style="margin:0 0 8px;font-size:20px;font-weight:600;
                           color:#1a1a18;letter-spacing:-0.3px;">
                  Payment received
                </p>

                <p style="margin:0 0 24px;font-size:14px;color:#5a5a56;line-height:1.65;">
                  Hi {cust_name}, thank you for your support.
                  Your payment has been successfully processed.
                </p>

                <!-- Receipt box -->
                <table width="100%" cellpadding="0" cellspacing="0"
                       style="background:#f8f7f4;border:1px solid #e0ddd6;
                              border-radius:10px;margin-bottom:24px;">
                  <tr>
                    <td style="padding:18px 20px;">
                      <p style="margin:0 0 12px;font-size:12px;
                                text-transform:uppercase;letter-spacing:1px;
                                color:#9a9a94;">
                        Receipt
                      </p>

                      <table width="100%">
                        <tr>
                          <td style="font-size:14px;color:#5a5a56;padding:4px 0;">
                            Amount
                          </td>
                          <td align="right"
                              style="font-size:16px;font-weight:600;color:#1a1a18;">
                            {amount}
                          </td>
                        </tr>

                        <tr>
                          <td style="font-size:14px;color:#5a5a56;padding:4px 0;">
                            Reason
                          </td>
                          <td align="right"
                              style="font-size:14px;color:#1a1a18;">
                            Audio export support (2 weeks)
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                </table>

                <p style="margin:0;font-size:13px;color:#5a5a56;line-height:1.65;">
                  {reason}
                </p>

              </td>
            </tr>

            <!-- Footer -->
            <tr>
              <td style="padding:18px 36px;border-top:1px solid #e0ddd6;
                         background:#f0efe9;">
                <p style="margin:0;font-size:11px;color:#9a9a94;line-height:1.6;">
                  Thank you for supporting Solfer.<br><br>
                  &copy; 2025 Solfer
                </p>
              </td>
            </tr>

          </table>

        </td></tr>
      </table>

    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Solfer receipt"
    msg["From"] = f"Solfer <{SMTP_CUST_SERVICE_MAIL}>"
    msg["To"] = email_dest

    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_KEY)
        server.sendmail(SMTP_USER, email_dest, msg.as_string())


if __name__ == "__main__":
  send_receipt_email(
      email_dest="francium49@outlook.com",
      cust_name="Francium",
      amount="100",
      reason="Audio export support (2 weeks)",)






    