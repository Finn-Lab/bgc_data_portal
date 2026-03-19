// Bind example keyword shortcut if present
(function(){
  var exampleLink = document.getElementById('example-link');
  if (!exampleLink) return;
  exampleLink.addEventListener('click', function (event) {
      event.preventDefault();  // Prevent the default link behavior
      const searchInput = document.getElementById('search-keyword');
      if (searchInput) {
        searchInput.value = 'Polyketide';  // Set the value of the input field
      }
      // Optionally, submit the form automatically
      // document.getElementById('keyword-form').submit();
  });
})();

// Global spinner helpers
function getGlobalSpinner() {
  return document.querySelector('.bgcs-portal-spinner');
}

function showGlobalSpinner() {
  var spinner = getGlobalSpinner();
  if (spinner) spinner.style.display = 'block';
}

function hideGlobalSpinner() {
  var spinner = getGlobalSpinner();
  if (spinner) spinner.style.display = 'none';
}

window.addEventListener('DOMContentLoaded', () => {
  // Attach spinner behavior to all known forms
  const formIds = ['keyword-form', 'search-form', 'sequence-search-form', 'chemical-search-form'];
  formIds.forEach(id => {
    const form = document.getElementById(id);
    if (!form) return;
    form.addEventListener('submit', () => {
      showGlobalSpinner();
      // Only disable submit buttons to prevent double-submit; disabling all inputs strips them from the GET query string
      form.querySelectorAll('button[type="submit"]').forEach(el => (el.disabled = true));
    });
  });
});


// document.addEventListener('DOMContentLoaded', function () {
//     const advancedForm = document.getElementById('search-form');
//     const loader = document.querySelector('.bgcs-portal-spinner');

//     if (advancedForm && loader) {
//       advancedForm.addEventListener('submit', function (event) {
//         console.log('Form submit event triggered');

//         event.preventDefault();
//         $('.bgcs-portal-spinner').show();

//         const formData = new FormData(advancedForm);

//         for (let [name, value] of formData.entries()) {
//           console.log(name, value);
//         }

//         const serializedData = new URLSearchParams(formData).toString();
//         const actionUrl = advancedForm.getAttribute('action');

//         console.log(`${actionUrl}?${serializedData}`);
//         window.location.href = `${actionUrl}?${$('#search-form').serialize()}`;
//       });
//     } else {
//       console.error('Form or Loader not found');
//     }
//   });

  // Handle pagination button clicks
  $(document).on('click', '.pagination button', function (e) {
    e.preventDefault();
    var page = $(this).data('page');

    // show spinner during pagination
    showGlobalSpinner();

    $.ajax({
      url: $('#search-form').attr('action'),
      type: 'GET',
      data: serializedString + '&page=' + page,
      success: function (response) {
        $('#results').html(response);
      },
      error: function (xhr, status, error) {
        console.error('AJAX Error:', status, error);
        $('#results').html('<p>An error occurred. Please try again.</p>');
      },
      complete: function () {
        hideGlobalSpinner();
      },
    });
  });

// Also toggle spinner automatically on any jQuery AJAX activity
$(document).ajaxStart(function(){ showGlobalSpinner(); });
$(document).ajaxStop(function(){ hideGlobalSpinner(); });
