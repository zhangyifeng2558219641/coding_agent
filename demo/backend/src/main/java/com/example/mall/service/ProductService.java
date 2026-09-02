package com.example.mall.service;

import com.example.mall.entity.Product;
import com.example.mall.repository.ProductRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.List;

/**
 * 商品服务:商品 CRUD、上下架、列表/详情(筛选/搜索/排序)
 */
@Service
public class ProductService {

    private final ProductRepository productRepository;

    @Autowired
    public ProductService(ProductRepository productRepository) {
        this.productRepository = productRepository;
    }

    /** 用户端列表:仅上架商品 */
    public List<Product> listForUser(String category, String keyword, String sort, String order) {
        return productRepository.listOnSale(category, keyword, sort, order);
    }

    /** 管理端列表:全部(含下架) */
    public List<Product> listForAdmin() {
        return productRepository.listAll();
    }

    public List<String> listCategories() {
        return productRepository.listCategories();
    }

    /** 用户端详情:仅上架商品 */
    public Product getForUser(Long id) {
        Product product = productRepository.findById(id);
        if (product == null || !"ON_SALE".equals(product.getStatus())) {
            throw new IllegalArgumentException("商品不存在或已下架");
        }
        return product;
    }

    /** 管理端详情:任意状态 */
    public Product getForAdmin(Long id) {
        Product product = productRepository.findById(id);
        if (product == null) {
            throw new IllegalArgumentException("商品不存在: id=" + id);
        }
        return product;
    }

    public Product create(String name, String category, String description, String imageUrl,
                          BigDecimal price, Integer stock, String status) {
        validate(name, price, stock);
        Product p = new Product();
        p.setName(name.trim());
        p.setCategory(category);
        p.setDescription(description);
        p.setImageUrl(imageUrl);
        p.setPrice(price);
        p.setStock(stock);
        p.setStatus("OFF_SHELF".equalsIgnoreCase(status) ? "OFF_SHELF" : "ON_SALE");
        Long id = productRepository.insert(p);
        p.setId(id);
        return productRepository.findById(id);
    }

    public Product update(Long id, String name, String category, String description, String imageUrl,
                          BigDecimal price, Integer stock) {
        Product exist = getForAdmin(id);
        validate(name, price, stock);
        exist.setName(name.trim());
        exist.setCategory(category);
        exist.setDescription(description);
        exist.setImageUrl(imageUrl);
        exist.setPrice(price);
        exist.setStock(stock);
        productRepository.update(exist);
        return productRepository.findById(id);
    }

    public Product updateStatus(Long id, String status) {
        getForAdmin(id);
        if (!"ON_SALE".equals(status) && !"OFF_SHELF".equals(status)) {
            throw new IllegalArgumentException("status 只能为 ON_SALE 或 OFF_SHELF");
        }
        productRepository.updateStatus(id, status);
        return productRepository.findById(id);
    }

    private void validate(String name, BigDecimal price, Integer stock) {
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("商品名称不能为空");
        }
        if (price == null || price.compareTo(BigDecimal.ZERO) < 0) {
            throw new IllegalArgumentException("价格不能为负");
        }
        if (stock == null || stock < 0) {
            throw new IllegalArgumentException("库存不能为负");
        }
    }
}
