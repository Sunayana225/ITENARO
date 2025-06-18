// Modal logic for Add Article
const addArticleBtn = document.getElementById('addArticleBtn');
const blogFormModal = document.getElementById('blogFormModal');
const closeModalBtn = document.getElementById('closeModalBtn');

if (addArticleBtn && blogFormModal && closeModalBtn) {
    addArticleBtn.onclick = function() {
        blogFormModal.style.display = 'flex';
    };
    closeModalBtn.onclick = function() {
        blogFormModal.style.display = 'none';
    };
    window.onclick = function(event) {
        if (event.target === blogFormModal) {
            blogFormModal.style.display = 'none';
        }
    };
}

// Filter logic for country/state
const countryFilter = document.getElementById('countryFilter');
const stateFilter = document.getElementById('stateFilter');
const blogPosts = document.getElementById('blogPosts');

function filterPosts() {
    const country = countryFilter.value;
    const state = stateFilter.value;
    const posts = blogPosts.querySelectorAll('.blog-post');
    posts.forEach(post => {
        const postCountry = post.getAttribute('data-country');
        const postState = post.getAttribute('data-state');
        let show = true;
        if (country && postCountry !== country) show = false;
        if (state && postState !== state) show = false;
        post.style.display = show ? '' : 'none';
    });
}
if (countryFilter && stateFilter) {
    countryFilter.addEventListener('change', filterPosts);
    stateFilter.addEventListener('change', filterPosts);
} 