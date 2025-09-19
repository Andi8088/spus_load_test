from flask import Flask, render_template, request, jsonify, send_from_directory
import time
import random
import threading
import requests
from datetime import datetime
import json
from collections import deque
import logging
from typing import Dict, List, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# In-memory storage for test history (in production, use a database)
test_history = deque(maxlen=50)  # Store last 50 tests

class LoadTestResult:
    def __init__(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.response_times = []
        self.start_time = None
        self.end_time = None
        self.concurrent_users = 0
        self.test_duration = 0

    def to_dict(self):
        return {
            'total_requests': self.total_requests,
            'successful_requests': self.successful_requests,
            'failed_requests': self.failed_requests,
            'avg_response_time': self.avg_response_time,
            'min_response_time': self.min_response_time,
            'max_response_time': self.max_response_time,
            'p95_response_time': self.p95_response_time,
            'p99_response_time': self.p99_response_time,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'concurrent_users': self.concurrent_users,
            'test_duration': self.test_duration,
            'success_rate': self.success_rate,
            'requests_per_second': self.requests_per_second
        }

    @property
    def avg_response_time(self):
        return sum(self.response_times) / len(self.response_times) if self.response_times else 0

    @property
    def min_response_time(self):
        return min(self.response_times) if self.response_times else 0

    @property
    def max_response_time(self):
        return max(self.response_times) if self.response_times else 0

    @property
    def p95_response_time(self):
        if not self.response_times:
            return 0
        sorted_times = sorted(self.response_times)
        index = int(len(sorted_times) * 0.95)
        return sorted_times[index]

    @property
    def p99_response_time(self):
        if not self.response_times:
            return 0
        sorted_times = sorted(self.response_times)
        index = int(len(sorted_times) * 0.99)
        return sorted_times[index]

    @property
    def success_rate(self):
        return (self.successful_requests / self.total_requests * 100) if self.total_requests > 0 else 0

    @property
    def requests_per_second(self):
        if not self.start_time or not self.end_time or self.total_requests == 0:
            return 0
        duration = (self.end_time - self.start_time).total_seconds()
        return self.total_requests / duration if duration > 0 else 0

# Mock payment gateway simulation
@app.route('/api/payment/process', methods=['POST'])
def process_payment():
    # Simulate processing time (100-500ms)
    processing_time = random.uniform(0.1, 0.5)
    time.sleep(processing_time)
    
    # Simulate occasional failures (5% failure rate)
    if random.random() < 0.05:
        logger.warning(f"Payment processing failed (simulated) - Time: {processing_time:.3f}s")
        return jsonify({
            'status': 'failed',
            'message': 'Payment processing failed',
            'processing_time': processing_time
        }), 500
    
    logger.info(f"Payment processed successfully - Time: {processing_time:.3f}s")
    return jsonify({
        'status': 'success',
        'message': 'Payment processed successfully',
        'processing_time': processing_time,
        'transaction_id': f"TXN{random.randint(100000, 999999)}"
    })

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/loadtest')
def loadtest():
    return render_template('loadtest.html')

@app.route('/report')
def report():
    return render_template('report.html', test_history=list(test_history))

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

@app.route('/api/run-load-test', methods=['POST'])
def run_load_test():
    data = request.json
    users = data.get('users', 10)
    duration = data.get('duration', 30)
    
    logger.info(f"Starting load test with {users} users for {duration} seconds")
    
    result = LoadTestResult()
    result.start_time = datetime.now()
    result.concurrent_users = users
    result.test_duration = duration
    
    # Lock for thread-safe operations
    lock = threading.Lock()
    
    def simulate_user(user_id):
        nonlocal result, lock
        start_time = time.time()
        try:
            # Simulate different payment scenarios
            payment_data = {
                'amount': random.randint(10, 1000),
                'card_number': '4111111111111111',
                'expiry': '12/25',
                'cvv': '123',
                'user_id': user_id,
                'timestamp': datetime.now().isoformat()
            }
            
            response = requests.post(
                'http://localhost:5000/api/payment/process',
                json=payment_data,
                timeout=2
            )
            end_time = time.time()
            
            response_time_ms = (end_time - start_time) * 1000
            
            with lock:
                result.total_requests += 1
                if response.status_code == 200:
                    result.successful_requests += 1
                else:
                    result.failed_requests += 1
                result.response_times.append(response_time_ms)
            
        except requests.exceptions.Timeout:
            end_time = time.time()
            response_time_ms = (end_time - start_time) * 1000
            with lock:
                result.total_requests += 1
                result.failed_requests += 1
                result.response_times.append(response_time_ms)
            logger.error(f"User {user_id}: Request timeout")
            
        except Exception as e:
            end_time = time.time()
            response_time_ms = (end_time - start_time) * 1000
            with lock:
                result.total_requests += 1
                result.failed_requests += 1
                result.response_times.append(response_time_ms)
            logger.error(f"User {user_id}: Error - {str(e)}")
    
    # Run load test with threads
    threads = []
    for i in range(users):
        t = threading.Thread(target=simulate_user, args=(i+1,))
        threads.append(t)
        t.start()
        # Stagger thread starts slightly to simulate real user behavior
        time.sleep(0.01)
    
    # Wait for all threads to complete or timeout
    for t in threads:
        t.join(timeout=duration + 5)  # Add buffer to timeout
    
    # Check for any still-running threads
    for t in threads:
        if t.is_alive():
            logger.warning(f"Thread {t.name} did not complete in time")
    
    result.end_time = datetime.now()
    
    # Store test result in history
    test_history.append(result.to_dict())
    
    logger.info(f"Load test completed: {result.total_requests} requests, "
                f"{result.successful_requests} successful, "
                f"{result.failed_requests} failed")
    
    return jsonify(result.to_dict())

@app.route('/api/test-history', methods=['GET'])
def get_test_history():
    """API endpoint to retrieve test history"""
    return jsonify(list(test_history))

@app.route('/api/performance-metrics', methods=['GET'])
def get_performance_metrics():
    """API endpoint to get aggregated performance metrics"""
    if not test_history:
        return jsonify({})
    
    # Calculate averages across all tests
    metrics = {
        'total_tests': len(test_history),
        'avg_success_rate': sum(t['success_rate'] for t in test_history) / len(test_history),
        'avg_response_time': sum(t['avg_response_time'] for t in test_history) / len(test_history),
        'avg_throughput': sum(t['requests_per_second'] for t in test_history) / len(test_history),
        'total_requests': sum(t['total_requests'] for t in test_history),
        'total_successful': sum(t['successful_requests'] for t in test_history),
        'total_failed': sum(t['failed_requests'] for t in test_history)
    }
    
    return jsonify(metrics)

@app.route('/api/system-status', methods=['GET'])
def get_system_status():
    """API endpoint to check system status"""
    return jsonify({
        'status': 'operational',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0',
        'tests_conducted': len(test_history)
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Print startup message
    print("=" * 50)
    print("SPUS Payment Gateway Load Testing System")
    print("Version: 1.0.0")
    print("Server starting on http://localhost:5000")
    print("Endpoints:")
    print("  - GET  / : Main dashboard")
    print("  - GET  /loadtest : Load testing interface")
    print("  - GET  /report : Performance reports")
    print("  - POST /api/payment/process : Mock payment endpoint")
    print("  - POST /api/run-load-test : Execute load test")
    print("  - GET  /api/test-history : Get test history")
    print("  - GET  /api/performance-metrics : Get performance metrics")
    print("=" * 50)
    
    app.run(debug=True, threaded=True, host='0.0.0.0', port=5000)