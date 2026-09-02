package com.example.mall.controller;

import com.example.mall.entity.Product;
import com.example.mall.entity.Review;
import com.example.mall.repository.ReviewRepository;
import com.example.mall.service.ProductService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 用户端商品控制器(公开):
 * GET /api/products                 商品列表(仅上架,筛选/搜索/排序)
 * GET /api/products/categories      分类列表
 * GET /api/products/{id}            商品详情(仅上架)
 * GET /api/products/{id}/reviews    商品评价列表
 */
@RestController
@RequestMapping("/api/products")
public class ProductController {

    private final ProductService productService;
    private final ReviewRepository reviewRepository;

    @Autowired
    public ProductController(ProductService productService, ReviewRepository reviewRepository) {
        this.productService = productService;
        this.reviewRepository = reviewRepository;
    }

    @GetMapping
    public List<Product> list(@RequestParam(required = false) String category,
                              @RequestParam(required = false) String keyword,
                              @RequestParam(required = false) String sort,
                              @RequestParam(defaultValue = "desc") String order) {
        return productService.listForUser(category, keyword, sort, order);
    }

    @GetMapping("/categories")
    public List<String> categories() {
        return productService.listCategories();
    }

    @GetMapping("/{id}")
    public Product detail(@PathVariable Long id) {
        return productService.getForUser(id);
    }

    @GetMapping("/{id}/reviews")
    public List<Review> reviews(@PathVariable Long id) {
        // 校验商品存在且上架,再返回评价
        productService.getForUser(id);
        return reviewRepository.listByProduct(id);
    }
}
