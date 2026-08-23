function renderFooter() {
  const el = document.getElementById('footer');
  if (!el) return;

  el.innerHTML = `
    <div class="footer-inner">
      <div class="footer-tagline">&#127915;&#65039; Ticket Booking</div>
      <p class="footer-sub">Movies and concerts, seats held while you decide, and a real
        ticket in your inbox the moment you're done.</p>
      <div class="footer-cols">
        <div class="footer-col">
          <h4>Browse</h4>
          <a href="/index.html">All events</a>
          <a href="/register.html">Create account</a>
          <a href="/login.html">Log in</a>
        </div>
        <div class="footer-col">
          <h4>My account</h4>
          <a href="/bookings.html">Booking history</a>
        </div>
        <div class="footer-col">
          <h4>For organisers &amp; admins</h4>
          <a href="/organiser.html">Organiser dashboard</a>
          <a href="/admin.html">Admin dashboard</a>
        </div>
      </div>
      <div class="footer-bottom">&copy; Ticket Booking</div>
    </div>
  `;
}

document.addEventListener('DOMContentLoaded', renderFooter);
