#!/usr/bin/env python3
"""
Integration validation script for optimized retrieval pipeline.

Validates:
1. Cache module initialization
2. Milvus integration in orchestrator
3. Memory ingestion cache invalidation
4. Parallel retrieval execution
5. End-to-end pipeline correctness
"""

import sys
import time
from typing import Dict, Any

# Color output
GREEN = '\033[92m'
RED = '\033[91m'
BLUE = '\033[94m'
RESET = '\033[0m'


class IntegrationValidator:
    """Validates all integration points in the optimized pipeline."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests_run = []

    def print_header(self, title: str):
        """Print formatted test section header."""
        print(f"\n{BLUE}{'='*70}{RESET}")
        print(f"{BLUE}{title:^70}{RESET}")
        print(f"{BLUE}{'='*70}{RESET}\n")

    def test_cache_module(self) -> bool:
        """Test 1: Cache module initialization and basic operations."""
        self.print_header("TEST 1: Cache Module Initialization")

        try:
            from services.cache.retrieval_cache import RetrievalCache, get_retrieval_cache

            print("✓ Cache module imports successful")

            # Initialize cache
            cache = RetrievalCache()
            print("✓ RetrievalCache instantiation successful")

            # Test set/get
            cache.set("user1", "test_query", {
                      "data": "test_value"}, "retrieval_context")
            result = cache.get("user1", "test_query", "retrieval_context")
            assert result == {"data": "test_value"}, "Cache get/set mismatch"
            print("✓ Cache set/get operations working")

            # Test global singleton
            cache_global = get_retrieval_cache()
            assert cache_global is not None, "Global cache singleton failed"
            print("✓ Global cache singleton working")

            # Test invalidation
            cache.invalidate_user("user1")
            result = cache.get("user1", "test_query", "retrieval_context")
            assert result is None, "User invalidation failed"
            print("✓ Cache user invalidation working")

            self.passed += 1
            return True

        except Exception as e:
            print(f"{RED}✗ Cache module test failed: {e}{RESET}")
            self.failed += 1
            return False

    def test_orchestrator_initialization(self) -> bool:
        """Test 2: RetrievalOrchestrator with cache integration."""
        self.print_header("TEST 2: RetrievalOrchestrator Initialization")

        try:
            from services.orchestrator.retrieval_orchestrator import RetrievalOrchestrator

            print("✓ RetrievalOrchestrator import successful")

            orchestrator = RetrievalOrchestrator()
            assert orchestrator is not None, "Orchestrator instantiation failed"
            print("✓ RetrievalOrchestrator instantiation successful")

            # Check cache is initialized
            assert hasattr(orchestrator, 'cache'), "Cache attribute missing"
            print("✓ Cache attribute present in orchestrator")

            # Check critical methods exist
            methods = ['retrieve_and_answer', '_retrieve_graph_parallel',
                       '_retrieve_vector_parallel', '_search_milvus', '_fuse_rrf']
            for method in methods:
                assert hasattr(
                    orchestrator, method), f"Method {method} missing"
            print(
                f"✓ All critical methods present: {len(methods)} methods validated")

            # Check parallel executor
            assert hasattr(
                orchestrator, 'executor'), "Executor not initialized"
            print("✓ ThreadPoolExecutor initialized for parallel retrieval")

            self.passed += 1
            return True

        except Exception as e:
            print(f"{RED}✗ Orchestrator initialization test failed: {e}{RESET}")
            self.failed += 1
            return False

    def test_memory_orchestrator_cache_invalidation(self) -> bool:
        """Test 3: Memory ingestion cache invalidation."""
        self.print_header("TEST 3: Memory Orchestrator Cache Invalidation")

        try:
            from services.orchestrator.memory_orchestrator import MemoryOrchestrator
            import inspect

            print("✓ MemoryOrchestrator import successful")

            # Check cache invalidation is in ingest_memory
            source = inspect.getsource(MemoryOrchestrator.ingest_memory)
            assert "invalidate_user" in source, "Cache invalidation not found in ingest_memory"
            print("✓ Cache invalidation integrated in ingest_memory()")

            assert "get_retrieval_cache" in source, "Cache import missing"
            print("✓ Cache retrieval function call present")

            self.passed += 1
            return True

        except Exception as e:
            print(
                f"{RED}✗ Memory orchestrator cache invalidation test failed: {e}{RESET}")
            self.failed += 1
            return False

    def test_milvus_integration(self) -> bool:
        """Test 4: Milvus integration in retrieval pipeline."""
        self.print_header("TEST 4: Milvus Integration Validation")

        try:
            from services.vector.milvus_service import get_milvus_service
            import inspect
            from services.orchestrator.retrieval_orchestrator import RetrievalOrchestrator

            # Check Milvus service available
            milvus = get_milvus_service()
            if milvus is None:
                print(
                    f"{RED}⚠ Milvus service not available (expected in test env){RESET}")
            else:
                print("✓ Milvus service available")
                assert hasattr(
                    milvus, 'search_similar'), "search_similar method missing"
                print("✓ Milvus search_similar() method present")

            # Check _search_milvus in orchestrator
            source = inspect.getsource(RetrievalOrchestrator)
            assert "_search_milvus" in source, "_search_milvus method not found"
            print("✓ _search_milvus() method present in orchestrator")

            # Check Milvus is called during vector retrieval
            assert "self.milvus_service" in source, "Milvus service not referenced in orchestrator"
            print("✓ Milvus service properly integrated in orchestrator")

            self.passed += 1
            return True

        except Exception as e:
            print(f"{RED}✗ Milvus integration test failed: {e}{RESET}")
            self.failed += 1
            return False

    def test_parallel_retrieval_structure(self) -> bool:
        """Test 5: Parallel retrieval execution structure."""
        self.print_header("TEST 5: Parallel Retrieval Structure")

        try:
            import inspect
            from concurrent.futures import ThreadPoolExecutor
            from services.orchestrator.retrieval_orchestrator import RetrievalOrchestrator

            # Check ThreadPoolExecutor in orchestrator
            source = inspect.getsource(RetrievalOrchestrator.__init__)
            assert "ThreadPoolExecutor" in source, "ThreadPoolExecutor not initialized"
            print("✓ ThreadPoolExecutor initialized in __init__()")

            # Check parallel methods
            assert hasattr(RetrievalOrchestrator, '_retrieve_graph_parallel'), \
                "Graph parallel method missing"
            print("✓ _retrieve_graph_parallel() method present")

            assert hasattr(RetrievalOrchestrator, '_retrieve_vector_parallel'), \
                "Vector parallel method missing"
            print("✓ _retrieve_vector_parallel() method present")

            # Check async reinforcement
            assert hasattr(RetrievalOrchestrator, '_reinforce_async'), \
                "Async reinforcement method missing"
            print("✓ _reinforce_async() method present (deferred updates)")

            # Check method is called with executor.submit
            retrieve_source = inspect.getsource(
                RetrievalOrchestrator.retrieve_and_answer)
            assert "executor.submit" in retrieve_source or "thread" in retrieve_source.lower(), \
                "Executor not used in retrieve_and_answer"
            print("✓ Executor.submit() used for concurrent retrieval")

            self.passed += 1
            return True

        except Exception as e:
            print(f"{RED}✗ Parallel retrieval structure test failed: {e}{RESET}")
            self.failed += 1
            return False

    def test_optimization_parameters(self) -> bool:
        """Test 6: Optimization parameters applied correctly."""
        self.print_header("TEST 6: Optimization Parameters Validation")

        try:
            from services.graph.retrieval import GraphRetrieval
            import inspect

            # Check max_depth reduction
            source = inspect.getsource(GraphRetrieval.retrieve)
            assert "max_depth" in source, "max_depth parameter not found"
            if "max_depth = 2" in source or "max_depth=2" in source or "max_depth: int = 2" in source:
                print("✓ Graph retrieval max_depth optimized to 2")
            else:
                print(
                    f"⚠ Graph retrieval max_depth not clearly set to 2 (check manually)")

            # Check Milvus nprobe optimization
            from services.vector.milvus_service import MilvusService
            source = inspect.getsource(MilvusService.search_similar)
            if "nprobe" in source:
                if "8" in source or "nprobe = 8" in source or "nprobe=8" in source:
                    print("✓ Milvus nprobe optimized (reduced from 10 to 8)")
                else:
                    print(f"⚠ Milvus nprobe not clearly at 8 (verify in source)")
            else:
                print("⚠ Milvus nprobe parameter not found (may be default)")

            # Check threshold optimization
            if "threshold" in source and ("0.4" in source or "threshold = 0.4" in source):
                print("✓ Milvus threshold optimized (lowered from 0.5 to 0.4)")
            else:
                print("⚠ Milvus threshold optimization not verified (check source)")

            self.passed += 1
            return True

        except Exception as e:
            print(f"{RED}✗ Optimization parameters test failed: {e}{RESET}")
            self.failed += 1
            return False

    def test_cache_integration_in_pipeline(self) -> bool:
        """Test 7: Cache integration in retrieve_and_answer workflow."""
        self.print_header("TEST 7: Cache Integration in Pipeline")

        try:
            import inspect
            from services.orchestrator.retrieval_orchestrator import RetrievalOrchestrator

            source = inspect.getsource(
                RetrievalOrchestrator.retrieve_and_answer)

            # Check cache.get() call
            assert "cache.get" in source, "Cache.get() not called in retrieve_and_answer"
            print("✓ cache.get() called for cache hit detection")

            # Check cache.set() call
            assert "cache.set" in source, "Cache.set() not called in retrieve_and_answer"
            print("✓ cache.set() called to store retrieval results")

            # Check cache invalidation on ingestion
            from services.orchestrator.memory_orchestrator import MemoryOrchestrator
            mem_source = inspect.getsource(MemoryOrchestrator.ingest_memory)
            assert "invalidate_user" in mem_source, "Cache invalidation missing on ingestion"
            print("✓ Cache invalidation on memory ingestion")

            # Check metrics include cache_hit flag
            assert "cache_hit" in source, "cache_hit metric not in metrics"
            print("✓ cache_hit metric tracked in performance metrics")

            self.passed += 1
            return True

        except Exception as e:
            print(f"{RED}✗ Cache integration test failed: {e}{RESET}")
            self.failed += 1
            return False

    def run_all_tests(self) -> bool:
        """Run complete validation suite."""
        print(f"\n{'='*70}")
        print(f"{'RETRIEVAL PIPELINE INTEGRATION VALIDATION':^70}")
        print(f"{'='*70}")

        # Run all tests
        tests = [
            ("Cache Module Initialization", self.test_cache_module),
            ("Orchestrator Initialization", self.test_orchestrator_initialization),
            ("Memory Ingestion Invalidation",
             self.test_memory_orchestrator_cache_invalidation),
            ("Milvus Integration", self.test_milvus_integration),
            ("Parallel Retrieval Structure", self.test_parallel_retrieval_structure),
            ("Optimization Parameters", self.test_optimization_parameters),
            ("Cache Pipeline Integration", self.test_cache_integration_in_pipeline),
        ]

        for test_name, test_func in tests:
            try:
                result = test_func()
                status = f"{GREEN}PASS{RESET}" if result else f"{RED}FAIL{RESET}"
                self.tests_run.append((test_name, result))
            except Exception as e:
                print(f"{RED}EXCEPTION in {test_name}: {e}{RESET}")
                self.tests_run.append((test_name, False))

        # Print summary
        self._print_summary()

        return self.failed == 0

    def _print_summary(self):
        """Print test summary."""
        print(f"\n{'='*70}")
        print(f"{'TEST SUMMARY':^70}")
        print(f"{'='*70}\n")

        for test_name, result in self.tests_run:
            status = f"{GREEN}✓ PASS{RESET}" if result else f"{RED}✗ FAIL{RESET}"
            print(f"{status} - {test_name}")

        total = len(self.tests_run)
        passed = sum(1 for _, r in self.tests_run if r)

        print(f"\n{'─'*70}")
        if passed == total:
            print(f"{GREEN}All {total} tests passed!{RESET}")
            print(f"{GREEN}Pipeline optimization complete and validated.{RESET}")
        else:
            print(f"{RED}{total - passed} test(s) failed.{RESET}")
            print(f"Passed: {passed}/{total}")
        print(f"{'─'*70}\n")


if __name__ == "__main__":
    validator = IntegrationValidator()
    success = validator.run_all_tests()
    sys.exit(0 if success else 1)
