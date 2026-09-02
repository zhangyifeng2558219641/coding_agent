package com.example.mall.config;

import com.example.mall.entity.Product;
import com.example.mall.repository.ProductRepository;
import com.example.mall.repository.UserRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.CommandLineRunner;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;

/**
 * 种子数据初始化(幂等):启动时若库中无账号/商品则创建。
 * 账号:
 *   管理员  admin@mall.com   / admin123456  (ADMIN)
 *   演示用户 demo@example.com / demo123456   (USER)
 * 商品:10 个演示商品(覆盖 数码/服饰/生活/食品 分类,含 1 个下架商品用于演示上下架)
 */
@Component
public class DataInitializer implements CommandLineRunner {

    private static final Logger log = LoggerFactory.getLogger(DataInitializer.class);

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private ProductRepository productRepository;

    @Override
    public void run(String... args) {
        BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();

        if (userRepository.findByEmail("admin@mall.com") == null) {
            userRepository.insert(buildUser("商城管理员", "admin@mall.com", encoder.encode("admin123456"), "ADMIN"));
            log.info("种子数据: 创建管理员 admin@mall.com / admin123456");
        }
        if (userRepository.findByEmail("demo@example.com") == null) {
            userRepository.insert(buildUser("演示用户", "demo@example.com", encoder.encode("demo123456"), "USER"));
            log.info("种子数据: 创建演示用户 demo@example.com / demo123456");
        }

        if (productRepository.count() == 0) {
            insertProduct("无线蓝牙耳机", "数码", "主动降噪,超长续航 30 小时,入耳式设计", "", "199.00", 100, "ON_SALE");
            insertProduct("机械键盘 87 键", "数码", "青轴手感,RGB 背光,Type-C 键线分离", "", "399.00", 50, "ON_SALE");
            insertProduct("4K 显示器 27 英寸", "数码", "IPS 面板,10bit 色深,窄边框设计", "", "1499.00", 30, "ON_SALE");
            insertProduct("纯棉短袖 T 恤", "服饰", "新疆长绒棉,亲肤透气,多色可选", "", "79.00", 200, "ON_SALE");
            insertProduct("休闲运动鞋", "服饰", "轻便缓震,透气网面,日常通勤百搭", "", "259.00", 80, "ON_SALE");
            insertProduct("帆布双肩包", "服饰", "大容量,防泼水帆布,多隔层设计", "", "129.00", 120, "ON_SALE");
            insertProduct("保温杯 500ml", "生活", "316 不锈钢内胆,24 小时保温保冷", "", "59.00", 300, "ON_SALE");
            insertProduct("香薰蜡烛礼盒", "生活", "大豆蜡,天然精油,三款香型组合装", "", "99.00", 60, "OFF_SHELF");
            insertProduct("咖啡豆 500g", "食品", "中度烘焙,阿拉比卡拼配,现磨现售", "", "88.00", 150, "ON_SALE");
            insertProduct("坚果零食大礼包", "食品", "每日坚果混合装,独立小包,新鲜烘焙", "", "128.00", 90, "ON_SALE");
            log.info("种子数据: 创建 10 个演示商品");
        }
    }

    private void insertProduct(String name, String category, String description, String imageUrl,
                               String price, int stock, String status) {
        Product p = new Product();
        p.setName(name);
        p.setCategory(category);
        p.setDescription(description);
        p.setImageUrl(imageUrl);
        p.setPrice(new BigDecimal(price));
        p.setStock(stock);
        p.setStatus(status);
        productRepository.insert(p);
    }

    private com.example.mall.entity.User buildUser(String nickname, String email, String hash, String role) {
        com.example.mall.entity.User u = new com.example.mall.entity.User();
        u.setUsername(nickname);
        u.setNickname(nickname);
        u.setEmail(email);
        u.setPasswordHash(hash);
        u.setRole(role);
        u.setPoints(0);
        return u;
    }
}
