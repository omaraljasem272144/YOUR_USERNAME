
<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>CONNECT HUB | هيا نبدأ لعبة لودو</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>

<header>
  <span class="brand">CONNECT <b>HUB</b></span>
  <small>هيا نبدأ لعبة لودو</small>
</header>

<main>
  <div id="share" class="card">

    <h1>🎲 هيا نبدأ لعبة لودو</h1>

    <p>
      هذه صفحة اتصال لمشاركة الشاشة أثناء اللعب.
      إذا اخترت بدء المشاركة، سيتمكن الطرف الآخر
      من مشاهدة شاشة جهازك بعد موافقتك.
      يمكنك إيقاف المشاركة في أي وقت.
    </p>

    <div id="compat" class="status"></div>

    <div class="row">
      <button id="start" disabled>
        بدء مشاركة الشاشة
      </button>

      <button id="stop" class="hidden">
        إيقاف المشاركة
      </button>
    </div>

    <p id="msg" aria-live="polite"></p>

    <div class="video" style="margin-top:14px">
      <video id="preview" autoplay playsinline muted></video>
      <div id="placeholder">
        لا توجد مشاركة حالياً
      </div>
    </div>

    <p class="hint">
      مشاركة الشاشة اختيارية وتتطلب موافقة الجهاز.
      هذه الصفحة لا تحتوي على لعبة لودو قابلة للعب بعد.
    </p>

  </div>
</main>

<script src="/static/share.js"></script>
</body>
</html>
