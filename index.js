document.querySelector('.menu-header').addEventListener('click', function() {
  const submenu = document.querySelector('.submenu');
  const arrow = this.querySelector('.arrow');
  
  if (submenu.style.display === 'none') {
    submenu.style.display = 'block';
    arrow.textContent = '▼';
  } else {
    submenu.style.display = 'none';
    arrow.textContent = '▲';
  }
});