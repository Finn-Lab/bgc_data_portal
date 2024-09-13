document.getElementById('example-link').addEventListener('click', function (event) {
    event.preventDefault();  // Prevent the default link behavior
    const searchInput = document.getElementById('search-keyword');
    searchInput.value = 'Polyketide';  // Set the value of the input field

    // Optionally, submit the form automatically
    // document.getElementById('keyword-form').submit();
});

window.onload = function () {
    // Select the form and loader directly
    const form = document.getElementById('keyword-form');
    const loader = document.getElementById('search-loader');

    // Ensure the elements are found before adding the listener
    if (form) {
        form.addEventListener('submit', function (event) {
            // Prevent the default form submission
            event.preventDefault();

            // Get the value of the 'keyword' input
            const keyword = form.querySelector('input[name="keyword"]').value;

            // Show the loader
            $('.bgcs-portal-spinner').show();

            // Disable form inputs to prevent multiple submissions
            form.querySelectorAll('input, button').forEach(element => element.disabled = true);

            // Construct the URL with the query parameters
            const actionUrl = form.getAttribute('action'); // Get the form action URL
            // const queryString = new URLSearchParams(new FormData(form)).toString(); // Serialize form data to query string

            // Redirect to the constructed URL
            window.location.href = `${actionUrl}?keyword=${keyword}`;
        });
    }
};


document.addEventListener('DOMContentLoaded', function () {
    const advancedForm = document.getElementById('search-form');
    const loader = document.querySelector('.bgcs-portal-spinner');
  
    if (advancedForm && loader) {
      advancedForm.addEventListener('submit', function (event) {
        console.log('Form submit event triggered');
  
        event.preventDefault();
        $('.bgcs-portal-spinner').show();
  
        const formData = new FormData(advancedForm);
  
        for (let [name, value] of formData.entries()) {
          console.log(name, value);
        }
  
        const serializedData = new URLSearchParams(formData).toString();
        const actionUrl = advancedForm.getAttribute('action');
  
        console.log(`${actionUrl}?${serializedData}`);
        window.location.href = `${actionUrl}?${$('#search-form').serialize()}`;
      });
    } else {
      console.error('Form or Loader not found');
    }
  });
  
  // Handle pagination button clicks
  $(document).on('click', '.pagination button', function (e) {
    e.preventDefault();
    var page = $(this).data('page');
  
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
        $('.bgcs-portal-spinner').hide();
      },
    });
  });
  
  function showSpinner() {
    var spinner = document.querySelector('.bgcs-portal-spinner'); // Select the spinner element
    if (spinner) {
        spinner.style.display = 'block'; // Show the spinner
    }
}