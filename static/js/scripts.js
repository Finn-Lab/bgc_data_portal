document.addEventListener('DOMContentLoaded', function() {
    const loader = document.getElementById('loader');
  
    // Show the loader before navigating away
    window.addEventListener('beforeunload', function() {
      loader.style.display = 'block';
    });
  
    // Hide the loader once the content has loaded
    window.addEventListener('load', function() {
      loader.style.display = 'none';
    });
  });