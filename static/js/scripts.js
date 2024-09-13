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


