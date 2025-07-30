What about img tags that use the src attr?
What about sites that are developed with Angular or other frameworks and attr like routerlink?

curl -X POST http://127.0.0.1:8000/crawl -H "Content-Type: application/json" -d '{"start_url":"https://nitpy.ac.in"}'
curl -X POST http://127.0.0.1:8000/crawl -H "Content-Type: application/json" -d "{\"start_url\":\"https://nitpy.ac.in\"}"
curl -X POST http://127.0.0.1:8000/crawl -H "Content-Type: application/json" -d "{\"start_url\":\"https://3dbykeerthi.netlify.app\"}"
curl -X POST http://127.0.0.1:8000/crawl -H "Content-Type: application/json" -d "{\"start_url\":\"https://dreaserous.netlify.app\"}"


uvicorn app.main:app --reload

Python 3.11.13


curl -X POST http://127.0.0.1:8000/rag -H "Content-Type: application/json" -d "{\"query\": \"Under what areas has this animator worked?\"}"
curl -X POST http://127.0.0.1:8000/rag -H "Content-Type: application/json" -d "{\"query\": \"What is the Animator's Name\"}"
curl -X POST http://127.0.0.1:8000/embed

curl -X POST http://127.0.0.1:8000/rag -H "Content-Type: application/json" -d "{\"query\": \"What are some upcoming events?\"}"
