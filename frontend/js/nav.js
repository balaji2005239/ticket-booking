function renderNav() {
  const nav = document.getElementById('nav');
  if (!nav) return;

  const user = getUser();
  let links = `<a href="/index.html">Browse Events</a>`;

  if (user) {
    if (user.role === 'customer') {
      links += ` &middot; <a href="/bookings.html">My Bookings</a>`;
    } else if (user.role === 'organiser') {
      links += ` &middot; <a href="/organiser.html">Organiser Dashboard</a>`;
    } else if (user.role === 'admin') {
      links += ` &middot; <a href="/admin.html">Admin</a>`;
    }
    links += ` &middot; <span class="muted">${escapeHtml(user.name)} (${escapeHtml(user.role)})</span>` +
      ` &middot; <a href="#" id="logoutLink">Logout</a>`;
  } else {
    links += ` &middot; <a href="/login.html">Login</a> &middot; <a href="/register.html">Register</a>`;
  }

  nav.innerHTML = `
    <div class="navbar">
      <a class="brand" href="/index.html">&#127915;&#65039; Ticket Booking</a>
      <div class="navlinks">${links}</div>
    </div>`;

  const logoutLink = document.getElementById('logoutLink');
  if (logoutLink) {
    logoutLink.addEventListener('click', (e) => {
      e.preventDefault();
      clearToken();
      location.href = '/index.html';
    });
  }
}

document.addEventListener('DOMContentLoaded', renderNav);
